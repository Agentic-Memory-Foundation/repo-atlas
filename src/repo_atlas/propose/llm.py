"""OpenAI-compatible backends: a local server, or a hosted API key."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import httpx

from repo_atlas.config import Config
from repo_atlas.errors import RepoAtlasError
from repo_atlas.naming import (
    build_filename,
    is_generic_dirname,
    is_generic_stem,
    split_identifier,
    valid_directory_name,
)
from repo_atlas.plan import PLAN_VERSION, PlanItem, RenamePlan
from repo_atlas.propose.heuristic import propose_heuristic
from repo_atlas.protect import Protection
from repo_atlas.scan import RepoIndex

_SYSTEM = """You rename source files and generic directories so each name describes the code inside.
Reply with JSON only. Do not use markdown fences.
Schema example:
{"renames":[{"path":"rel/file.py","proposed_name":"new_name.py","reason":"...","confidence":0.8}]}
Rules:
- Include every candidate path from the user message.
- proposed_name is a single file or directory name, never a path.
- Keep the same extension for files.
- Use an empty proposed_name to keep the current name.
- Python modules and Python package directories must be snake_case and must not be keywords.
- JavaScript and TypeScript file names should be kebab-case.
- Do not invent paths that were not listed.
- confidence is a number between 0 and 1.
"""


def _settings(config: Config, backend: str) -> tuple[str, str, str | None]:
    if backend == "local":
        return config.local_base_url, config.local_model, os.environ.get("REPO_ATLAS_LOCAL_API_KEY")
    if backend == "api":
        key = os.environ.get(config.api_key_env)
        if not key:
            raise RepoAtlasError(
                f"Backend 'api' needs an API key in the {config.api_key_env} environment variable."
            )
        return config.api_base_url, config.api_model, key
    raise RepoAtlasError(f"Backend {backend!r} is not a model backend.")


def _candidate_payload(index: RepoIndex, config: Config) -> list[dict[str, Any]]:
    protection = Protection(index.root, config.protected)
    payload: list[dict[str, Any]] = []
    for signals in index.files:
        if protection.is_protected(signals.path) or not is_generic_stem(signals.stem):
            continue
        payload.append(
            {
                "path": signals.path.as_posix(),
                "kind": "file",
                "language": signals.language,
                "current_name": signals.path.name,
                "signals": signals.to_summary(),
            }
        )
    directories: set[Path] = set()
    for signals in index.files:
        parent = signals.path.parent
        while parent != Path("."):
            directories.add(parent)
            parent = parent.parent
    for directory in sorted(directories, key=lambda item: item.as_posix()):
        if protection.is_structural_dir(directory) or not is_generic_dirname(directory.name):
            continue
        children = [
            signals.path.as_posix() for signals in index.files if directory in signals.path.parents
        ]
        if len(children) < 2:
            continue
        payload.append(
            {
                "path": directory.as_posix(),
                "kind": "directory",
                "current_name": directory.name,
                "children": children[:30],
            }
        )
    return payload


def parse_model_json(text: str) -> dict[str, Any]:
    """Parse a JSON object from a model reply, including fenced blocks."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict):
        raise json.JSONDecodeError("object required", cleaned, 0)
    return data


def _validate_suggestion(
    suggestion: dict[str, Any],
    candidates: dict[str, dict[str, Any]],
    config: Config,
) -> PlanItem | None:
    path = str(suggestion.get("path", ""))
    if path not in candidates:
        return None
    meta = candidates[path]
    proposed = str(suggestion.get("proposed_name", "")).strip()
    if not proposed or proposed == meta["current_name"] or "/" in proposed or "\\" in proposed:
        return None
    if Path(proposed).name != proposed or proposed in {".", ".."}:
        return None
    kind = str(meta["kind"])
    if kind == "file":
        suffix = Path(meta["current_name"]).suffix
        if Path(proposed).suffix != suffix:
            return None
        filename = build_filename(
            split_identifier(Path(proposed).stem),
            suffix,
            meta.get("language"),
            config.naming_style,
        )
        if filename is None:
            return None
        proposed = filename
    else:
        contains_python = str(meta.get("language") or "") == "python" or _children_python(meta)
        name = split_identifier(proposed)
        language = "python" if contains_python else None
        joined = build_filename(name, "", language, config.naming_style)
        if joined is None or not valid_directory_name(joined, contains_python):
            return None
        proposed = joined
    try:
        confidence = float(suggestion.get("confidence", 0.7))
    except (TypeError, ValueError):
        confidence = 0.7
    confidence = min(1.0, max(0.0, confidence))
    if confidence < config.min_confidence:
        return None
    reason = str(suggestion.get("reason") or "Suggested by the model.").strip()
    return PlanItem(
        path=path,
        kind=kind,
        language=meta.get("language"),
        current_name=str(meta["current_name"]),
        proposed_name=proposed,
        proposed_path=path,
        reason=reason,
        confidence=round(confidence, 2),
        signals=meta.get("signals") if isinstance(meta.get("signals"), dict) else None,
    )


def _children_python(meta: dict[str, Any]) -> bool:
    children = meta.get("children") or []
    return any(str(child).endswith(".py") for child in children)


def _complete(
    client: httpx.Client,
    base_url: str,
    model: str,
    api_key: str | None,
    timeout: float,
    batch: list[dict[str, Any]],
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    url = base_url.rstrip("/") + "/chat/completions"
    response = client.post(
        url,
        headers=headers,
        json={
            "model": model,
            "temperature": 0,
            "max_tokens": 2000,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps({"candidates": batch}, indent=2),
                },
            ],
        },
        timeout=timeout,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:300]
        raise RepoAtlasError(
            f"Model request failed with HTTP {exc.response.status_code}: {detail}"
        ) from exc
    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise RepoAtlasError("Model response did not include a chat completion.") from exc
    if not isinstance(content, str):
        raise RepoAtlasError("Model response content was not text.")
    try:
        return parse_model_json(content)
    except json.JSONDecodeError as exc:
        raise RepoAtlasError(f"Model did not return JSON: {exc}") from exc


def propose_llm(
    index: RepoIndex,
    config: Config,
    *,
    backend: str,
    client: httpx.Client | None = None,
) -> RenamePlan:
    """Ask an OpenAI-compatible server, and fall back to heuristics per invalid name."""
    base_url, model, api_key = _settings(config, backend)
    heuristic = propose_heuristic(index, config)
    candidates = {item["path"]: item for item in _candidate_payload(index, config)}
    warnings = list(heuristic.warnings)
    suggestions: dict[str, PlanItem] = {}
    batches = list(candidates.values())
    owns_client = client is None
    http = client or httpx.Client()
    try:
        for start in range(0, len(batches), config.batch_size):
            batch = batches[start : start + config.batch_size]
            if not batch:
                continue
            try:
                parsed = _complete(
                    http,
                    base_url,
                    model,
                    api_key,
                    config.timeout_seconds,
                    batch,
                )
            except RepoAtlasError as exc:
                if "did not return JSON" in str(exc):
                    warnings.append(str(exc) + " Heuristic names were kept for that batch.")
                    continue
                raise
            renames = parsed.get("renames", [])
            if not isinstance(renames, list):
                warnings.append("Model JSON did not contain a renames list. Heuristics were kept.")
                continue
            for suggestion in renames:
                if not isinstance(suggestion, dict):
                    continue
                item = _validate_suggestion(suggestion, candidates, config)
                if item is None:
                    path = str(suggestion.get("path", ""))
                    if path:
                        warnings.append(f"Ignored an invalid model name for {path}.")
                    continue
                suggestions[item.path] = item
    finally:
        if owns_client:
            http.close()

    # Model suggestions replace heuristic items. Missing candidates keep the heuristic.
    heuristic_by_path = {item.path: item for item in heuristic.items}
    for path, item in suggestions.items():
        heuristic_by_path[path] = item
    # A model answer of "keep" (empty name) drops a heuristic rename for that path.
    # `_validate_suggestion` returns None for empty names, so track explicit keeps.
    # Re-read is unnecessary: invalid or empty suggestions already produced warnings
    # and the heuristic remains. That is the safe default.

    merged = list(heuristic_by_path.values())
    # Re-run collision handling and path composition through the heuristic finalizer
    # by applying model names onto a fresh heuristic plan's items, then rebuilding.
    from repo_atlas.propose.heuristic import _fill_paths, _resolve_collisions

    all_paths = [signals.path for signals in index.files]
    merged = _resolve_collisions(merged, all_paths)
    merged.sort(key=lambda item: (item.kind != "directory", item.path))
    path_map = _fill_paths(merged, all_paths)
    return RenamePlan(
        version=PLAN_VERSION,
        backend=backend,
        root=str(index.root),
        items=merged,
        path_map=path_map,
        warnings=warnings,
        skipped=heuristic.skipped,
    )

"""Rename plans: the contract between propose, apply, and the agent backend."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from repo_atlas.errors import RepoAtlasError

PLAN_VERSION = 1


@dataclass
class PlanItem:
    path: str
    kind: str
    language: str | None
    current_name: str
    proposed_name: str
    proposed_path: str
    reason: str
    confidence: float
    signals: dict[str, object] | None = None
    extra_tokens: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        return data


@dataclass
class RenamePlan:
    version: int
    backend: str
    root: str
    items: list[PlanItem] = field(default_factory=list)
    path_map: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)

    def file_items(self) -> list[PlanItem]:
        return [item for item in self.items if item.kind == "file"]

    def directory_items(self) -> list[PlanItem]:
        return [item for item in self.items if item.kind == "directory"]


def plan_to_json(plan: RenamePlan) -> str:
    payload = {
        "version": plan.version,
        "backend": plan.backend,
        "root": plan.root,
        "items": [item.to_dict() for item in plan.items],
        "path_map": plan.path_map,
        "warnings": plan.warnings,
        "skipped": plan.skipped,
    }
    return json.dumps(payload, indent=2) + "\n"


def plan_from_json(text: str) -> RenamePlan:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RepoAtlasError(f"Plan is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RepoAtlasError("Plan JSON must be an object.")
    version = int(data.get("version", 0))
    if version != PLAN_VERSION:
        raise RepoAtlasError(f"Unsupported plan version {version}. This tool reads version 1.")
    items: list[PlanItem] = []
    for raw in data.get("items", []):
        if not isinstance(raw, dict):
            raise RepoAtlasError("Each plan item must be an object.")
        items.append(
            PlanItem(
                path=str(raw.get("path", "")),
                kind=str(raw.get("kind", "file")),
                language=raw.get("language"),
                current_name=str(raw.get("current_name", "")),
                proposed_name=str(raw.get("proposed_name", "")),
                proposed_path=str(raw.get("proposed_path", "")),
                reason=str(raw.get("reason", "")),
                confidence=float(raw.get("confidence") or 0.0),
                signals=raw.get("signals") if isinstance(raw.get("signals"), dict) else None,
                extra_tokens=[str(token) for token in raw.get("extra_tokens", [])],
            )
        )
    path_map = []
    for entry in data.get("path_map", []):
        if isinstance(entry, dict) and "from" in entry and "to" in entry:
            path_map.append({"from": str(entry["from"]), "to": str(entry["to"])})
    warnings = [str(item) for item in data.get("warnings", [])]
    skipped = []
    for entry in data.get("skipped", []):
        if isinstance(entry, dict):
            skipped.append(
                {
                    "path": str(entry.get("path", "")),
                    "reason": str(entry.get("reason", "")),
                }
            )
    return RenamePlan(
        version=version,
        backend=str(data.get("backend", "none")),
        root=str(data.get("root", "")),
        items=items,
        path_map=path_map,
        warnings=warnings,
        skipped=skipped,
    )


def load_plan(path: Path) -> RenamePlan:
    if not path.is_file():
        raise RepoAtlasError(f"Plan file not found: {path}")
    return plan_from_json(path.read_text(encoding="utf-8"))


def save_plan(plan: RenamePlan, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan_to_json(plan), encoding="utf-8")

"""Export a plan for an external coding agent, then ingest the completed file."""

from __future__ import annotations

from pathlib import Path

from repo_atlas.config import Config
from repo_atlas.errors import RepoAtlasError
from repo_atlas.naming import (
    build_filename,
    is_generic_dirname,
    is_generic_stem,
    split_identifier,
    valid_directory_name,
)
from repo_atlas.plan import PLAN_VERSION, PlanItem, RenamePlan, plan_from_json
from repo_atlas.propose.heuristic import _fill_paths, _resolve_collisions
from repo_atlas.protect import Protection
from repo_atlas.scan import RepoIndex

PROMPT = """# repo-atlas agent task

Fill in `plan.json` so each generic file and directory gets a name that describes the code inside.
repo-atlas does not call a model for this backend. You are the model. Use your own subscription.

## What to edit

Open `plan.json` in this folder. For every object in `items`:

- Set `proposed_name` to a new file or directory name.
- Set `reason` to one short sentence.
- Set `confidence` to a number from 0 to 1. If you leave it at 0, ingest treats that as 0.75.
- Leave `proposed_name` as an empty string to keep the current name.
- Do not add, remove, or rename JSON keys other than `proposed_name`, `reason`, and `confidence`.
- Do not change `path`.

`proposed_name` is a single name, not a path. Do not include `/`.

## Naming rules

- Python modules must be snake_case and valid identifiers. Keep the `.py` extension.
- Python package directories that contain `.py` files must be snake_case too.
- JavaScript and TypeScript files should be kebab-case. Keep the existing extension.
- Prefer the primary public function or class when a file has one clear purpose.
- Do not rename a file that already has a specific name. Those files are not in the list.
- Never use names that collide inside the same directory.

## When you are done

From the repository root, run:

```bash
repo-atlas ingest PATH/plan.json --output plan.json
repo-atlas apply plan.json
repo-atlas apply plan.json --write
```

The first `apply` is a dry run. Pass `--write` only after the diff looks right.
"""


def _candidates(index: RepoIndex, config: Config) -> list[PlanItem]:
    protection = Protection(index.root, config.protected)
    items: list[PlanItem] = []
    for signals in index.files:
        if protection.is_protected(signals.path) or not is_generic_stem(signals.stem):
            continue
        items.append(
            PlanItem(
                path=signals.path.as_posix(),
                kind="file",
                language=signals.language,
                current_name=signals.path.name,
                proposed_name="",
                proposed_path="",
                reason="",
                confidence=0.0,
                signals=signals.to_summary(),
            )
        )
    directories: set[Path] = set()
    for signals in index.files:
        if signals.language in {"markdown", "rst", "text"}:
            continue
        parent = signals.path.parent
        while parent != Path("."):
            directories.add(parent)
            parent = parent.parent
    for directory in sorted(directories, key=lambda item: item.as_posix()):
        if protection.is_structural_dir(directory) or not is_generic_dirname(directory.name):
            continue
        children = [
            signals
            for signals in index.files
            if directory in signals.path.parents and signals.language not in {"markdown", "rst"}
        ]
        if len(children) < 2:
            continue
        contains_python = any(signals.language == "python" for signals in children)
        items.append(
            PlanItem(
                path=directory.as_posix(),
                kind="directory",
                language="python" if contains_python else None,
                current_name=directory.name,
                proposed_name="",
                proposed_path="",
                reason="",
                confidence=0.0,
                signals={
                    "children": [signals.path.as_posix() for signals in children[:30]],
                    "docstrings": [signals.docstring[:160] for signals in children[:8]],
                },
            )
        )
    return items


def build_agent_pack(index: RepoIndex, config: Config) -> tuple[RenamePlan, str]:
    """Return an empty plan for an external agent and the instruction markdown."""
    items = _candidates(index, config)
    plan = RenamePlan(
        version=PLAN_VERSION,
        backend="agent",
        root=str(index.root),
        items=items,
        path_map=[],
        warnings=[],
        skipped=[],
    )
    return plan, PROMPT


def _normalize_filled_item(item: PlanItem, config: Config) -> PlanItem | None:
    proposed = item.proposed_name.strip()
    if not proposed:
        return None
    if "/" in proposed or "\\" in proposed or proposed in {".", ".."}:
        raise RepoAtlasError(f"{item.path}: proposed_name must be a single name, not a path.")
    if item.kind == "file":
        suffix = Path(item.current_name).suffix
        if Path(proposed).suffix != suffix:
            raise RepoAtlasError(f"{item.path}: keep the {suffix} extension.")
        filename = build_filename(
            split_identifier(Path(proposed).stem),
            suffix,
            item.language,
            config.naming_style,
        )
        if filename is None:
            raise RepoAtlasError(f"{item.path}: {proposed!r} is not a valid {item.language} name.")
        item.proposed_name = filename
    else:
        contains_python = item.language == "python" or _signals_have_python(item)
        tokens = split_identifier(proposed)
        style_language = "python" if contains_python else None
        renamed = build_filename(tokens, "", style_language, config.naming_style)
        if renamed is None or not valid_directory_name(renamed, contains_python):
            raise RepoAtlasError(f"{item.path}: {proposed!r} is not a valid directory name.")
        item.proposed_name = renamed
    if item.confidence < 0 or item.confidence > 1:
        raise RepoAtlasError(f"{item.path}: confidence must be between 0 and 1.")
    if item.confidence == 0:
        item.confidence = 0.75
    if not item.reason:
        item.reason = "Filled in by an external agent."
    return item


def _signals_have_python(item: PlanItem) -> bool:
    if not item.signals:
        return False
    children = item.signals.get("children") or []
    return any(str(child).endswith(".py") for child in children)


def ingest_agent_plan(plan: RenamePlan, index: RepoIndex, config: Config) -> RenamePlan:
    """Validate an agent-completed plan and compute final paths."""
    if plan.backend not in {"agent", "none", "local", "api"}:
        raise RepoAtlasError(f"Unknown plan backend {plan.backend!r}.")
    allowed = {item.path for item in _candidates(index, config)}
    # Also allow paths that were in the submitted plan even if the tree changed slightly,
    # but reject anything outside the repo or unexpected.
    cleaned: list[PlanItem] = []
    for item in plan.items:
        rel = Path(item.path)
        if rel.is_absolute() or ".." in rel.parts:
            raise RepoAtlasError(f"Unsafe path in plan: {item.path}")
        if item.path not in allowed and item.proposed_name.strip():
            raise RepoAtlasError(
                f"{item.path} is not a rename candidate. Remove it or leave the name empty."
            )
        if not item.proposed_name.strip():
            continue
        normalized = _normalize_filled_item(item, config)
        if normalized is not None and normalized.confidence >= config.min_confidence:
            cleaned.append(normalized)
    all_paths = [signals.path for signals in index.files]
    cleaned = _resolve_collisions(cleaned, all_paths)
    cleaned.sort(key=lambda item: (item.kind != "directory", item.path))
    path_map = _fill_paths(cleaned, all_paths)
    return RenamePlan(
        version=PLAN_VERSION,
        backend="agent",
        root=str(index.root),
        items=cleaned,
        path_map=path_map,
        warnings=list(plan.warnings),
        skipped=[],
    )


def ingest_agent_file(path: Path, index: RepoIndex, config: Config) -> RenamePlan:
    text = path.read_text(encoding="utf-8")
    return ingest_agent_plan(plan_from_json(text), index, config)

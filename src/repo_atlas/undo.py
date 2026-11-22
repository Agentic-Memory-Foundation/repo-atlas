"""Undo manifests. Apply writes one, and `repo-atlas undo` reverses it."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from repo_atlas.errors import RepoAtlasError
from repo_atlas.gitutil import is_git_repo, run_git


def undo_root(root: Path) -> Path:
    """Keep undo data out of the work tree when the project is a git checkout."""
    git_dir = root / ".git"
    if git_dir.is_dir():
        return git_dir / "repo-atlas" / "undo"
    return root / ".repo-atlas" / "undo"


@dataclass
class UndoManifest:
    directory: Path
    created_at: str
    root: str
    renames: list[dict[str, str]] = field(default_factory=list)
    content_backups: list[dict[str, str]] = field(default_factory=list)

    @property
    def path(self) -> Path:
        return self.directory / "manifest.json"


def new_manifest(root: Path) -> UndoManifest:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = undo_root(root)
    directory = base / stamp
    suffix = 2
    while directory.exists():
        directory = base / f"{stamp}-{suffix}"
        suffix += 1
    directory.mkdir(parents=True, exist_ok=False)
    return UndoManifest(
        directory=directory,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        root=str(root),
    )


def save_manifest(manifest: UndoManifest) -> None:
    import json

    payload = {
        "version": 1,
        "created_at": manifest.created_at,
        "root": manifest.root,
        "renames": manifest.renames,
        "content_backups": manifest.content_backups,
    }
    manifest.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_manifest(path: Path) -> UndoManifest:
    import json

    manifest_path = path
    if path.is_dir():
        manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        raise RepoAtlasError(f"Undo manifest not found: {path}")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RepoAtlasError(f"Undo manifest is not valid JSON: {exc}") from exc
    if int(data.get("version", 0)) != 1:
        raise RepoAtlasError("Unsupported undo manifest version.")
    return UndoManifest(
        directory=manifest_path.parent,
        created_at=str(data.get("created_at", "")),
        root=str(data.get("root", "")),
        renames=list(data.get("renames", [])),
        content_backups=list(data.get("content_backups", [])),
    )


def latest_manifest(root: Path) -> UndoManifest:
    base = undo_root(root)
    if not base.is_dir():
        raise RepoAtlasError("No undo manifest found. Apply a plan with --write first.")
    found = sorted(path for path in base.glob("*/manifest.json") if path.is_file())
    if not found:
        raise RepoAtlasError("No undo manifest found. Apply a plan with --write first.")
    return load_manifest(found[-1])


def _move_back(root: Path, src: Path, dest: Path, *, use_git: bool) -> None:
    source = root / src
    target = root / dest
    if not source.exists():
        raise RepoAtlasError(f"Cannot undo: {src.as_posix()} is missing.")
    if target.exists():
        raise RepoAtlasError(f"Cannot undo: {dest.as_posix()} already exists.")
    target.parent.mkdir(parents=True, exist_ok=True)
    if use_git and is_git_repo(root):
        tracked = run_git(root, ["ls-files", "--", src.as_posix()], check=False)
        if tracked.stdout.strip():
            run_git(root, ["mv", src.as_posix(), dest.as_posix()])
            return
    shutil.move(str(source), str(target))


@dataclass
class UndoReport:
    dry_run: bool
    moves: list[tuple[str, str]]
    restored: list[str]
    manifest_path: str


def undo_manifest(
    root: Path,
    manifest: UndoManifest,
    *,
    write: bool,
    use_git: bool = True,
) -> UndoReport:
    """Reverse renames and restore rewritten file contents. Dry-run unless `write` is set."""
    root = root.resolve()
    moves = [(item["to"], item["from"]) for item in reversed(manifest.renames)]
    restored = [item["path"] for item in manifest.content_backups]
    report = UndoReport(
        dry_run=not write,
        moves=moves,
        restored=restored,
        manifest_path=str(manifest.path),
    )
    if not write:
        return report
    for item in manifest.content_backups:
        target = root / item["path"]
        backup = manifest.directory / item["backup"]
        if not backup.is_file():
            raise RepoAtlasError(f"Undo backup is missing: {backup}")
        if not target.is_file():
            raise RepoAtlasError(f"Cannot restore {item['path']}: the file is missing.")
        target.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
    for src, dest in moves:
        _move_back(root, Path(src), Path(dest), use_git=use_git)
    return report

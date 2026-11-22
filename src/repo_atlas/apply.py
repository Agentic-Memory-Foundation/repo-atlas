"""Apply a rename plan with git mv, then update imports. Dry-run unless asked to write."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from repo_atlas.errors import RepoAtlasError
from repo_atlas.gitutil import ensure_clean, is_git_repo, run_git
from repo_atlas.plan import RenamePlan
from repo_atlas.rewrite import RewriteContext, rewrite_source
from repo_atlas.undo import UndoManifest, new_manifest, save_manifest, undo_root

SWAP_DIR = Path(".repo-atlas-swap")


@dataclass
class TextChange:
    old_path: str
    new_path: str
    before: str
    after: str


@dataclass
class ApplyReport:
    dry_run: bool
    moves: list[tuple[str, str]] = field(default_factory=list)
    changes: list[TextChange] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manifest_path: str | None = None

    @property
    def changed(self) -> bool:
        return bool(self.moves or self.changes)


def _safe(path: Path) -> None:
    if path.is_absolute() or ".." in path.parts:
        raise RepoAtlasError(f"Unsafe path in plan: {path.as_posix()}")


def file_map_for(plan: RenamePlan, files: list[Path]) -> dict[Path, Path]:
    raw = {Path(entry["from"]): Path(entry["to"]) for entry in plan.path_map}
    mapped: dict[Path, Path] = {}
    for path in files:
        _safe(path)
        dest = raw.get(path, path)
        _safe(dest)
        mapped[path] = dest
    seen: dict[Path, Path] = {}
    for src, dest in mapped.items():
        if dest in seen and seen[dest] != src:
            raise RepoAtlasError(
                f"Rename collision: {seen[dest].as_posix()} and {src.as_posix()} "
                f"both move to {dest.as_posix()}."
            )
        seen[dest] = src
    return mapped


def dir_map_for(plan: RenamePlan) -> dict[Path, Path]:
    mapped: dict[Path, Path] = {}
    for item in plan.directory_items():
        src = Path(item.path)
        dest = Path(item.proposed_path or item.path)
        _safe(src)
        _safe(dest)
        if src != dest:
            mapped[src] = dest
    return mapped


def _order_moves(moves: list[tuple[Path, Path]]) -> list[tuple[Path, Path]]:
    """Order renames so a destination is free. Cycles go through a swap name."""
    pending: dict[Path, Path] = {}
    for src, dest in moves:
        if src == dest:
            continue
        if src in pending:
            raise RepoAtlasError(f"Duplicate rename source: {src.as_posix()}")
        pending[src] = dest
    ordered: list[tuple[Path, Path]] = []
    guard = 0
    while pending:
        guard += 1
        if guard > 10000:
            raise RepoAtlasError("Could not order renames without a cycle that will not break.")
        ready = [src for src, dest in pending.items() if dest not in pending]
        if ready:
            for src in sorted(ready, key=lambda item: item.as_posix()):
                ordered.append((src, pending.pop(src)))
            continue
        src = sorted(pending, key=lambda item: item.as_posix())[0]
        dest = pending.pop(src)
        token = f"{guard}-{src.name}"
        temp = SWAP_DIR / token
        while temp in pending or any(temp == existing for existing, _dest in ordered):
            token = f"{guard}-{token}"
            temp = SWAP_DIR / token
        ordered.append((src, temp))
        pending[temp] = dest
    return ordered


def compile_moves(plan: RenamePlan) -> list[tuple[Path, Path]]:
    """File basename moves first, then directory moves from the deepest path up."""
    file_moves: list[tuple[Path, Path]] = []
    for item in plan.file_items():
        src = Path(item.path)
        _safe(src)
        if not item.proposed_name or item.proposed_name == src.name:
            continue
        if "/" in item.proposed_name or "\\" in item.proposed_name:
            raise RepoAtlasError(f"{item.path}: proposed_name must be a file name.")
        file_moves.append((src, src.parent / item.proposed_name))
    dir_moves: list[tuple[Path, Path]] = []
    for item in plan.directory_items():
        src = Path(item.path)
        _safe(src)
        if not item.proposed_name or item.proposed_name == src.name:
            continue
        if "/" in item.proposed_name or "\\" in item.proposed_name:
            raise RepoAtlasError(f"{item.path}: proposed directory name must be one segment.")
        dir_moves.append((src, src.parent / item.proposed_name))
    dir_moves.sort(key=lambda pair: (len(pair[0].parts), pair[0].as_posix()), reverse=True)
    return _order_moves(file_moves) + _order_moves(dir_moves)


def _affected(paths: set[Path], src: Path) -> list[Path]:
    return [path for path in paths if path == src or src in path.parents]


def _simulate(paths: set[Path], moves: list[tuple[Path, Path]]) -> None:
    current = set(paths)
    for src, dest in moves:
        affected = _affected(current, src)
        if src not in affected and not affected:
            raise RepoAtlasError(f"Cannot rename missing path {src.as_posix()}.")
        if not affected and src in current:
            affected = [src]
        if src not in current and not affected:
            raise RepoAtlasError(f"Cannot rename missing path {src.as_posix()}.")
        for path in list(current):
            if path == dest or (dest in path.parents):
                if src == path or src in path.parents:
                    continue
                raise RepoAtlasError(
                    f"Refusing to overwrite {dest.as_posix()} while renaming {src.as_posix()}."
                )
        for path in affected:
            current.remove(path)
            if path == src:
                current.add(dest)
            else:
                current.add(dest / path.relative_to(src))


def compute_text_changes(
    root: Path,
    files: list[Path],
    plan: RenamePlan,
) -> list[TextChange]:
    ctx = RewriteContext(
        root=root,
        file_map=file_map_for(plan, files),
        dir_map=dir_map_for(plan),
    )
    changes: list[TextChange] = []
    for path in files:
        full = root / path
        if not full.is_file():
            continue
        try:
            before = full.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        after = rewrite_source(before, path, ctx)
        if after != before:
            dest = ctx.locate(path)
            assert dest is not None
            changes.append(
                TextChange(
                    old_path=path.as_posix(),
                    new_path=dest.as_posix(),
                    before=before,
                    after=after,
                )
            )
    return changes


def _tracked(root: Path, rel: Path) -> bool:
    listed = run_git(root, ["ls-files", "--", rel.as_posix()], check=False)
    return bool(listed.stdout.strip())


def _move(root: Path, src: Path, dest: Path, *, use_git: bool) -> None:
    source = root / src
    target = root / dest
    if not source.exists():
        raise RepoAtlasError(f"Cannot rename missing path {src.as_posix()}.")
    if target.exists():
        raise RepoAtlasError(f"Refusing to overwrite {dest.as_posix()}.")
    target.parent.mkdir(parents=True, exist_ok=True)
    if use_git and is_git_repo(root) and _tracked(root, src):
        run_git(root, ["mv", src.as_posix(), dest.as_posix()])
        if source.is_dir():
            for child in list(source.rglob("*")):
                if child.is_file():
                    relative = child.relative_to(source)
                    destination = target / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(child), str(destination))
            shutil.rmtree(source, ignore_errors=True)
        elif source.exists():
            shutil.move(str(source), str(target))
        return
    shutil.move(str(source), str(target))


def apply_plan(
    root: Path,
    plan: RenamePlan,
    *,
    files: list[Path],
    write: bool,
    force: bool = False,
    use_git: bool = True,
) -> ApplyReport:
    """Show the rename diff. Pass `write=True` to perform it and record an undo manifest."""
    root = root.resolve()
    if use_git and write and not is_git_repo(root) and not force:
        raise RepoAtlasError(
            "This directory is not a git repository. Initialize git, or pass --no-git "
            "to rename files without git mv."
        )
    moves = compile_moves(plan)
    present = {path for path in files if (root / path).exists()}
    for item in plan.directory_items():
        directory = Path(item.path)
        if (root / directory).is_dir():
            present.add(directory)
    if moves:
        _simulate(set(present), moves)
    changes = compute_text_changes(root, files, plan)
    report = ApplyReport(
        dry_run=not write,
        moves=[(src.as_posix(), dest.as_posix()) for src, dest in moves],
        changes=changes,
        warnings=list(plan.warnings),
    )
    if not write:
        return report
    if use_git:
        ensure_clean(root, force=force)
    manifest: UndoManifest | None = None
    if moves or changes:
        manifest = new_manifest(root)
        for change in changes:
            backup = manifest.directory / "files" / change.new_path
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_text(change.before, encoding="utf-8")
            manifest.content_backups.append(
                {"path": change.new_path, "backup": f"files/{change.new_path}"}
            )
        for src, dest in moves:
            _move(root, src, dest, use_git=use_git)
            manifest.renames.append({"from": src.as_posix(), "to": dest.as_posix()})
        for change in changes:
            target = root / change.new_path
            if not target.is_file():
                raise RepoAtlasError(
                    f"Expected {change.new_path} after renames so imports could be updated."
                )
            target.write_text(change.after, encoding="utf-8")
        save_manifest(manifest)
        report.manifest_path = str(manifest.path)
        swap = root / SWAP_DIR
        if swap.is_dir():
            try:
                swap.rmdir()
            except OSError:
                pass
    elif write:
        report.warnings.append("Nothing to rename.")
    return report


def manifest_dir_for(root: Path) -> Path:
    return undo_root(root)

"""Small git helpers used by apply and undo."""

from __future__ import annotations

import subprocess
from pathlib import Path

from repo_atlas.errors import RepoAtlasError


def is_git_repo(root: Path) -> bool:
    return (root / ".git").exists()


def run_git(root: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RepoAtlasError(detail or f"git {' '.join(args)} failed")
    return result


def dirty_entries(root: Path) -> list[str]:
    """Return tracked modifications. Untracked files do not count as a dirty tree."""
    if not is_git_repo(root):
        return []
    result = run_git(root, ["status", "--porcelain", "--untracked-files=no"])
    return [line for line in result.stdout.splitlines() if line.strip()]


def ensure_clean(root: Path, *, force: bool) -> None:
    if not is_git_repo(root):
        return
    entries = dirty_entries(root)
    if entries and not force:
        preview = "\n".join(entries[:12])
        extra = ""
        if len(entries) > 12:
            extra = f"\n... and {len(entries) - 12} more"
        raise RepoAtlasError(
            "Refusing to rename files in a dirty git tree. Commit or stash the changes, "
            f"or pass --force.\n{preview}{extra}"
        )

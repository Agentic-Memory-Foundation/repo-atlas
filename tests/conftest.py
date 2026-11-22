"""Shared fixtures for repository tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Repo Atlas",
    "GIT_AUTHOR_EMAIL": "atlas@example.com",
    "GIT_COMMITTER_NAME": "Repo Atlas",
    "GIT_COMMITTER_EMAIL": "atlas@example.com",
}


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def git_commit(root: Path, message: str = "init") -> None:
    env = os.environ.copy()
    env.update(GIT_ENV)
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True, env=env)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=root,
        check=True,
        capture_output=True,
        env=env,
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root

"""Load repo-atlas.toml and the pyproject tool section."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from repo_atlas.errors import RepoAtlasError
from repo_atlas.tomlutil import load_toml

BACKENDS = ("none", "local", "agent", "api")
NAMING_STYLES = ("auto", "snake", "kebab", "camel")


@dataclass
class Config:
    """Effective settings for one run. CLI flags override files, files override defaults."""

    backend: str = "none"
    naming_style: str = "auto"
    min_confidence: float = 0.5
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    protected: list[str] = field(default_factory=list)
    local_base_url: str = "http://127.0.0.1:11434/v1"
    local_model: str = "qwen2.5-coder:7b"
    api_base_url: str = "https://api.openai.com/v1"
    api_model: str = "gpt-4o-mini"
    api_key_env: str = "REPO_ATLAS_API_KEY"
    timeout_seconds: float = 60.0
    batch_size: int = 8
    root: Path = field(default_factory=Path.cwd)

    def validate(self) -> None:
        if self.backend not in BACKENDS:
            raise RepoAtlasError(
                f"Unknown backend {self.backend!r}. Choose one of: {', '.join(BACKENDS)}."
            )
        if self.naming_style not in NAMING_STYLES:
            raise RepoAtlasError(
                f"Unknown naming style {self.naming_style!r}. "
                f"Choose one of: {', '.join(NAMING_STYLES)}."
            )
        if not 0.0 <= self.min_confidence <= 1.0:
            raise RepoAtlasError("min_confidence must be between 0 and 1.")
        if self.batch_size < 1:
            raise RepoAtlasError("batch_size must be at least 1.")


def find_project_root(start: Path) -> Path:
    """Return the git root that contains `start`, or `start` itself."""
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return current


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    raise RepoAtlasError("include, exclude, and protected must be lists of globs.")


def _apply_table(config: Config, table: dict[str, Any]) -> None:
    if not table:
        return
    if "backend" in table:
        config.backend = str(table["backend"])
    if "naming_style" in table:
        config.naming_style = str(table["naming_style"])
    if "naming" in table and "naming_style" not in table:
        config.naming_style = str(table["naming"])
    if "min_confidence" in table:
        config.min_confidence = float(table["min_confidence"])
    if "include" in table:
        config.include = _as_str_list(table["include"])
    if "exclude" in table:
        config.exclude = _as_str_list(table["exclude"])
    if "protected" in table:
        config.protected = _as_str_list(table["protected"])
    if "timeout_seconds" in table:
        config.timeout_seconds = float(table["timeout_seconds"])
    if "batch_size" in table:
        config.batch_size = int(table["batch_size"])
    local = table.get("local", {})
    if isinstance(local, dict):
        if "base_url" in local:
            config.local_base_url = str(local["base_url"])
        if "model" in local:
            config.local_model = str(local["model"])
    api = table.get("api", {})
    if isinstance(api, dict):
        if "base_url" in api:
            config.api_base_url = str(api["base_url"])
        if "model" in api:
            config.api_model = str(api["model"])
        if "api_key_env" in api:
            config.api_key_env = str(api["api_key_env"])


def _apply_env(config: Config) -> None:
    if os.environ.get("REPO_ATLAS_LOCAL_BASE_URL"):
        config.local_base_url = os.environ["REPO_ATLAS_LOCAL_BASE_URL"]
    if os.environ.get("REPO_ATLAS_LOCAL_MODEL"):
        config.local_model = os.environ["REPO_ATLAS_LOCAL_MODEL"]
    if os.environ.get("REPO_ATLAS_API_BASE_URL"):
        config.api_base_url = os.environ["REPO_ATLAS_API_BASE_URL"]
    if os.environ.get("REPO_ATLAS_API_MODEL"):
        config.api_model = os.environ["REPO_ATLAS_API_MODEL"]


def load_config(start: Path) -> Config:
    """Load defaults, then pyproject, then repo-atlas.toml, then environment variables."""
    root = find_project_root(start)
    config = Config(root=root)
    pyproject = load_toml(root / "pyproject.toml")
    tool = pyproject.get("tool", {})
    if isinstance(tool, dict):
        section = tool.get("repo-atlas", {})
        if isinstance(section, dict):
            _apply_table(config, section)
    repo_file = load_toml(root / "repo-atlas.toml")
    if repo_file:
        _apply_table(config, repo_file)
    _apply_env(config)
    config.validate()
    return config

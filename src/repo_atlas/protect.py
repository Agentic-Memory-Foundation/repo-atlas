"""Paths that repo-atlas must never rename."""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path

from pathspec import PathSpec

from repo_atlas.tomlutil import load_toml

# Basenames that frameworks and packaging tools require.
PROTECTED_BASENAMES = frozenset(
    {
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "package.json",
        "package-lock.json",
        "cargo.toml",
        "cargo.lock",
        "go.mod",
        "go.sum",
        "gemfile",
        "composer.json",
        "pipfile",
        "pipfile.lock",
        "poetry.lock",
        "uv.lock",
        "makefile",
        "dockerfile",
        "conftest.py",
        "manage.py",
        "wsgi.py",
        "asgi.py",
        "settings.py",
        "models.py",
        "views.py",
        "admin.py",
        "apps.py",
        "urls.py",
        "forms.py",
        "serializers.py",
        "__init__.py",
        "__main__.py",
        "index.js",
        "index.ts",
        "index.tsx",
        "index.jsx",
        "index.mjs",
        "index.cjs",
        "main.rs",
        "lib.rs",
        "mod.rs",
        "main.go",
        "middleware.ts",
        "middleware.js",
        "next.config.js",
        "next.config.ts",
        "next.config.mjs",
        "vite.config.ts",
        "vite.config.js",
        "webpack.config.js",
        "tailwind.config.js",
        "tailwind.config.ts",
        "postcss.config.js",
        "jest.config.js",
        "jest.config.ts",
        "vitest.config.ts",
        "vitest.config.js",
        "pytest.ini",
        "tox.ini",
        "noxfile.py",
        "ruff.toml",
        ".ruff.toml",
        ".gitignore",
        ".gitattributes",
        ".editorconfig",
        ".env",
        "license",
        "licence",
        "copying",
        "notice",
        "authors",
        "code_of_conduct.md",
        "contributing.md",
        "changelog.md",
        "security.md",
        "readme.md",
        "readme.rst",
        "readme.txt",
    }
)

PROTECTED_BASENAME_GLOBS = (
    "README*",
    "LICENSE*",
    "LICENCE*",
    "CHANGELOG*",
    "CONTRIBUTING*",
    "Dockerfile*",
    "docker-compose*.yml",
    "docker-compose*.yaml",
    "requirements*.txt",
    "tsconfig*.json",
    ".env*",
    ".prettierrc*",
    ".eslintrc*",
    "eslint.config.*",
)

# Test discovery names. Renaming them can hide tests from the runner.
TEST_BASENAME_GLOBS = (
    "test_*.py",
    "*_test.py",
    "tests.py",
    "*_test.go",
    "*_test.rs",
    "test_*.rb",
    "*_spec.rb",
    "*.test.js",
    "*.test.jsx",
    "*.test.ts",
    "*.test.tsx",
    "*.test.mjs",
    "*.spec.js",
    "*.spec.jsx",
    "*.spec.ts",
    "*.spec.tsx",
    "*.spec.mjs",
)

NEXT_CONVENTION_BASENAMES = frozenset(
    {
        "page.tsx",
        "page.ts",
        "page.jsx",
        "page.js",
        "layout.tsx",
        "layout.ts",
        "layout.jsx",
        "layout.js",
        "template.tsx",
        "template.ts",
        "template.jsx",
        "template.js",
        "loading.tsx",
        "loading.ts",
        "loading.jsx",
        "loading.js",
        "error.tsx",
        "error.ts",
        "error.jsx",
        "error.js",
        "not-found.tsx",
        "not-found.ts",
        "not-found.jsx",
        "not-found.js",
        "route.ts",
        "route.js",
        "default.tsx",
        "default.ts",
        "default.jsx",
        "default.js",
        "head.tsx",
        "head.ts",
        "robots.ts",
        "sitemap.ts",
        "opengraph-image.tsx",
        "icon.tsx",
        "icon.ts",
        "middleware.ts",
        "middleware.js",
    }
)

STRUCTURAL_DIR_NAMES = frozenset(
    {
        "src",
        "tests",
        "test",
        "docs",
        "doc",
        "node_modules",
        "vendor",
        "third_party",
        "third-party",
        "public",
        "static",
        "templates",
        "migrations",
        "alembic",
        "versions",
        "app",
        "pages",
        "components",
        "hooks",
        "styles",
        "assets",
        "bin",
        "scripts",
        "cmd",
        "internal",
        "pkg",
        "api",
        "dist",
        "build",
        "config",
        "configs",
        "fixtures",
        "bench",
        "examples",
        "example",
        "github",
        "cursor",
        "claude",
    }
)


def _matches_glob(name: str, patterns: tuple[str, ...] | list[str]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def is_migration(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    if path.suffix == ".py" and "migrations" in parts:
        return True
    if path.suffix == ".py" and "alembic" in parts and "versions" in parts:
        return True
    return False


def is_next_convention(path: Path) -> bool:
    if path.name not in NEXT_CONVENTION_BASENAMES:
        return False
    parents = {part for part in path.parts[:-1]}
    return "app" in parents or "pages" in parents


def is_dotpath(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)


def discover_entrypoints(root: Path) -> set[str]:
    """Return module names and relative paths declared as package entry points."""
    found: set[str] = set()
    package_json = root / "package.json"
    if package_json.is_file():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        if isinstance(data, dict):
            bin_field = data.get("bin")
            if isinstance(bin_field, str):
                found.add(bin_field)
            elif isinstance(bin_field, dict):
                found.update(str(value) for value in bin_field.values())
            main = data.get("main")
            if isinstance(main, str):
                found.add(main)
            module = data.get("module")
            if isinstance(module, str):
                found.add(module)
    pyproject = load_toml(root / "pyproject.toml")
    scripts = pyproject.get("project", {}).get("scripts", {})
    if isinstance(scripts, dict):
        for spec in scripts.values():
            if isinstance(spec, str) and ":" in spec:
                found.add(spec.split(":", 1)[0])
    return found


def module_name_for(path: Path) -> str:
    if path.name == "__init__.py":
        parts = path.parent.parts
    else:
        parts = path.with_suffix("").parts
    return ".".join(parts)


class Protection:
    """Protection rules for one repository."""

    def __init__(self, root: Path, extra_globs: list[str] | None = None) -> None:
        self.root = root
        self.extra_globs = list(extra_globs or [])
        self.entrypoints = discover_entrypoints(root)
        self._extra_spec = (
            PathSpec.from_lines("gitignore", self.extra_globs) if self.extra_globs else None
        )

    def reason(self, path: Path) -> str | None:
        """Return why `path` is protected, or None when it may be renamed."""
        if is_dotpath(path):
            return "hidden path"
        name = path.name
        lowered = name.lower()
        if lowered in PROTECTED_BASENAMES or name in PROTECTED_BASENAMES:
            return "protected file name"
        if _matches_glob(name, PROTECTED_BASENAME_GLOBS) or _matches_glob(
            lowered, PROTECTED_BASENAME_GLOBS
        ):
            return "protected file name"
        if _matches_glob(name, TEST_BASENAME_GLOBS):
            return "test discovery name"
        if is_migration(path):
            return "framework migration"
        if is_next_convention(path):
            return "framework convention path"
        rel = path.as_posix()
        if rel in self.entrypoints or name in self.entrypoints:
            return "package entry point"
        if path.suffix == ".py":
            dotted = module_name_for(path)
            candidates = {dotted}
            if dotted.startswith("src."):
                candidates.add(dotted[4:])
            if candidates & self.entrypoints:
                return "package entry point"
        if self._extra_spec is not None and (
            self._extra_spec.match_file(rel) or self._extra_spec.match_file(name)
        ):
            return "configured protected glob"
        for pattern in self.extra_globs:
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(name, pattern):
                return "configured protected glob"
        return None

    def is_protected(self, path: Path) -> bool:
        return self.reason(path) is not None

    def is_structural_dir(self, path: Path) -> bool:
        return path.name.lower() in STRUCTURAL_DIR_NAMES or is_dotpath(path)

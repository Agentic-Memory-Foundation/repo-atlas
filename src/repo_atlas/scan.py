"""Walk a repository and collect per-file signals."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from pathspec import PathSpec

from repo_atlas.config import Config
from repo_atlas.signals import FileSignals, extract_signals, language_for

SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "vendor",
        "third_party",
        "third-party",
        ".venv",
        "venv",
        "env",
        ".tox",
        "dist",
        "build",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".cache",
        "htmlcov",
        "coverage",
        ".next",
        ".nuxt",
        ".turbo",
        ".repo-atlas",
        "site-packages",
        ".eggs",
        "generated",
        "gen",
        "bower_components",
        ".gradle",
        "target",
    }
)

LOCK_AND_GENERATED_GLOBS = (
    "*.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
    "go.sum",
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.pyc",
    "*.pyo",
    "*_pb2.py",
    "*_pb2_grpc.py",
    "*.generated.*",
    "*.so",
    "*.dll",
    "*.dylib",
    "*.exe",
    "*.bin",
)

BINARY_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".pdf",
        ".zip",
        ".tar",
        ".gz",
        ".tgz",
        ".bz2",
        ".xz",
        ".7z",
        ".wasm",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".otf",
        ".mp3",
        ".mp4",
        ".mov",
        ".avi",
        ".sqlite",
        ".db",
        ".pickle",
        ".pkl",
        ".parquet",
        ".feather",
        ".pyc",
        ".pyo",
        ".class",
        ".jar",
        ".war",
        ".so",
        ".dll",
        ".dylib",
        ".exe",
        ".bin",
        ".o",
        ".a",
        ".lib",
    }
)

MAX_FILE_BYTES = 1_000_000


@dataclass
class Skipped:
    path: str
    reason: str


@dataclass
class RepoIndex:
    root: Path
    files: list[FileSignals] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)

    def by_path(self) -> dict[Path, FileSignals]:
        return {item.path: item for item in self.files}


class _IgnoreRules:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.specs: list[tuple[Path, PathSpec]] = []

    def load_dir(self, directory: Path) -> None:
        gitignore = directory / ".gitignore"
        if not gitignore.is_file():
            return
        try:
            text = gitignore.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        spec = PathSpec.from_lines("gitignore", text.splitlines())
        self.specs.append((directory.relative_to(self.root), spec))

    def ignored(self, rel: Path, is_dir: bool) -> bool:
        rel_posix = rel.as_posix()
        for base, spec in self.specs:
            base_posix = "." if base == Path(".") else base.as_posix()
            if base_posix == ".":
                candidate = rel_posix
            else:
                prefix = base_posix + "/"
                if rel_posix == base_posix or not rel_posix.startswith(prefix):
                    continue
                candidate = rel_posix[len(prefix) :]
            if is_dir:
                if spec.match_file(candidate) or spec.match_file(candidate + "/"):
                    return True
            elif spec.match_file(candidate):
                return True
        return False


def _matches_skip_file(path: Path) -> str | None:
    import fnmatch

    name = path.name
    for pattern in LOCK_AND_GENERATED_GLOBS:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(path.as_posix(), pattern):
            return "lock or generated file"
    if path.suffix.lower() in BINARY_SUFFIXES:
        return "binary extension"
    return None


def _looks_binary(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:8192]
    except OSError:
        return True
    return b"\0" in chunk


def _included(rel: Path, config: Config) -> bool:
    spec_text = rel.as_posix()
    if config.exclude:
        excluded = PathSpec.from_lines("gitignore", config.exclude)
        if excluded.match_file(spec_text):
            return False
    if config.include:
        included = PathSpec.from_lines("gitignore", config.include)
        return included.match_file(spec_text)
    return True


def scan_repo(root: Path, config: Config | None = None) -> RepoIndex:
    """Walk `root`, honor gitignore, and skip binaries, vendored, and generated files."""
    root = root.resolve()
    config = config or Config(root=root)
    index = RepoIndex(root=root)
    ignores = _IgnoreRules(root)
    ignores.load_dir(root)

    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        rel_dir = current.relative_to(root)
        if rel_dir != Path("."):
            ignores.load_dir(current)
        kept_dirs: list[str] = []
        for name in sorted(dirnames):
            child = rel_dir / name if rel_dir != Path(".") else Path(name)
            if name in SKIP_DIR_NAMES or name.endswith(".egg-info"):
                index.skipped.append(Skipped(child.as_posix(), "vendored or generated directory"))
                continue
            if ignores.ignored(child, is_dir=True):
                index.skipped.append(Skipped(child.as_posix(), "gitignored directory"))
                continue
            kept_dirs.append(name)
        dirnames[:] = kept_dirs

        for name in sorted(filenames):
            rel = rel_dir / name if rel_dir != Path(".") else Path(name)
            full = root / rel
            if full.is_symlink():
                index.skipped.append(Skipped(rel.as_posix(), "symlink"))
                continue
            if any(part.startswith(".") for part in rel.parts):
                index.skipped.append(Skipped(rel.as_posix(), "hidden path"))
                continue
            if ignores.ignored(rel, is_dir=False):
                index.skipped.append(Skipped(rel.as_posix(), "gitignored file"))
                continue
            skip_reason = _matches_skip_file(rel)
            if skip_reason:
                index.skipped.append(Skipped(rel.as_posix(), skip_reason))
                continue
            try:
                size = full.stat().st_size
            except OSError:
                index.skipped.append(Skipped(rel.as_posix(), "unreadable"))
                continue
            if size > MAX_FILE_BYTES:
                index.skipped.append(Skipped(rel.as_posix(), "file too large"))
                continue
            if _looks_binary(full):
                index.skipped.append(Skipped(rel.as_posix(), "binary file"))
                continue
            if not _included(rel, config):
                index.skipped.append(Skipped(rel.as_posix(), "excluded by config"))
                continue
            try:
                source = full.read_text(encoding="utf-8", errors="replace")
            except OSError:
                index.skipped.append(Skipped(rel.as_posix(), "unreadable"))
                continue
            if language_for(rel) is None and "\0" in source:
                index.skipped.append(Skipped(rel.as_posix(), "binary file"))
                continue
            index.files.append(extract_signals(rel, source))
    index.files.sort(key=lambda item: item.path.as_posix())
    return index

"""Rewriter protocol and the context apply passes to each language."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class RewriteContext:
    """Old path to new path for every scanned file, plus renamed directories."""

    root: Path
    file_map: dict[Path, Path]
    dir_map: dict[Path, Path] = field(default_factory=dict)

    def locate(self, path: Path | None) -> Path | None:
        if path is None:
            return None
        return self.file_map.get(path, path)


class ImportRewriter(Protocol):
    """Update references after files move. Register extra languages with `register_rewriter`."""

    def handles(self, path: Path) -> bool:
        """Return True when this rewriter understands `path`."""

    def rewrite(self, source: str, path: Path, ctx: RewriteContext) -> str:
        """Return updated source. `path` is the file's location before renames."""


_REGISTRY: list[ImportRewriter] = []


def register_rewriter(rewriter: ImportRewriter) -> None:
    """Add a rewriter. Later rewriters run after the built-in ones."""
    _REGISTRY.append(rewriter)


def get_rewriters() -> list[ImportRewriter]:
    return list(_REGISTRY)


def rewrite_source(source: str, path: Path, ctx: RewriteContext) -> str:
    updated = source
    for rewriter in _REGISTRY:
        if rewriter.handles(path):
            updated = rewriter.rewrite(updated, path, ctx)
    return updated

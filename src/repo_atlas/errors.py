"""User-facing errors."""

from __future__ import annotations


class RepoAtlasError(Exception):
    """An error the CLI should print without a traceback."""

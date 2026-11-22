"""TOML loading that works on Python 3.10 and newer."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML document. Missing files return an empty mapping."""
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    if sys.version_info >= (3, 11):
        import tomllib

        data = tomllib.loads(text)
    else:
        import tomli

        data = tomli.loads(text)
    if not isinstance(data, dict):
        return {}
    return data

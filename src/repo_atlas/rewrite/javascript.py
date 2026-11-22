"""Update JavaScript and TypeScript relative imports after files move."""

from __future__ import annotations

import os
import re
from pathlib import Path

from repo_atlas.rewrite.base import RewriteContext

_SPEC = re.compile(
    r"""(?P<prefix>\bfrom\s+|\brequire\s*\(\s*|\bimport\s*\(\s*|\bimport\s+)"""
    r"""(?P<quote>['\"])(?P<spec>[^'\"]+)(?P=quote)"""
)
_CODE_SUFFIXES = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")


def _commented(source: str, index: int) -> bool:
    line_start = source.rfind("\n", 0, index) + 1
    prefix = source[line_start:index].lstrip()
    return prefix.startswith("//") or prefix.startswith("*") or prefix.startswith("/*")


def resolve_specifier(root: Path, importer: Path, spec: str) -> Path | None:
    if not spec.startswith("."):
        return None
    raw = Path(os.path.normpath(str(importer.parent / spec)))
    if ".." in Path(spec).parts and str(raw).startswith(".."):
        return None
    if raw.is_absolute() or any(part == ".." for part in raw.parts):
        return None
    candidates: list[Path] = []
    if raw.suffix in _CODE_SUFFIXES:
        candidates.append(raw)
    else:
        for suffix in _CODE_SUFFIXES:
            candidates.append(Path(str(raw) + suffix))
        for suffix in _CODE_SUFFIXES:
            candidates.append(raw / f"index{suffix}")
    for candidate in candidates:
        if (root / candidate).is_file():
            return candidate
    return None


def _specifier(importer: Path, target: Path, original: str) -> str:
    rel = os.path.relpath(target.as_posix(), start=importer.parent.as_posix() or ".")
    rel = rel.replace(os.sep, "/")
    had_suffix = Path(original).suffix in _CODE_SUFFIXES
    if not had_suffix and Path(rel).suffix in _CODE_SUFFIXES:
        rel = str(Path(rel).with_suffix(""))
    if not rel.startswith("."):
        rel = f"./{rel}"
    return rel


class JavaScriptRewriter:
    """Rewrite relative `import`, `export from`, `require`, and dynamic `import()` specifiers."""

    def handles(self, path: Path) -> bool:
        return path.suffix in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}

    def rewrite(self, source: str, path: Path, ctx: RewriteContext) -> str:
        new_importer = ctx.locate(path)
        assert new_importer is not None
        edits: list[tuple[int, int, str]] = []
        for match in _SPEC.finditer(source):
            if _commented(source, match.start()):
                continue
            spec = match.group("spec")
            resolved = resolve_specifier(ctx.root, path, spec)
            if resolved is None:
                continue
            moved = ctx.locate(resolved)
            assert moved is not None
            if moved == resolved and new_importer == path:
                continue
            updated = _specifier(new_importer, moved, spec)
            if updated == spec:
                continue
            edits.append((match.start("spec"), match.end("spec"), updated))
        if not edits:
            return source
        updated_source = source
        for start, end, text in sorted(edits, key=lambda item: item[0], reverse=True):
            updated_source = updated_source[:start] + text + updated_source[end:]
        return updated_source

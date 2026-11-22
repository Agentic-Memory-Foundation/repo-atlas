"""Update markdown links and inline code paths after renames."""

from __future__ import annotations

from pathlib import Path

from repo_atlas.rewrite.base import RewriteContext


class MarkdownRewriter:
    """Replace exact relative paths inside markdown links and inline code."""

    def handles(self, path: Path) -> bool:
        return path.suffix.lower() in {".md", ".mdx"}

    def rewrite(self, source: str, path: Path, ctx: RewriteContext) -> str:
        del path
        replacements: list[tuple[str, str]] = []
        for old, new in ctx.file_map.items():
            if old != new:
                replacements.append((old.as_posix(), new.as_posix()))
        for old, new in ctx.dir_map.items():
            if old != new:
                replacements.append((old.as_posix(), new.as_posix()))
        replacements.sort(key=lambda item: len(item[0]), reverse=True)
        for old, new in replacements:
            source = source.replace(f"]({old})", f"]({new})")
            source = source.replace(f"`{old}`", f"`{new}`")
            source = source.replace(f"]({old}/)", f"]({new}/)")
            source = source.replace(f"`{old}/`", f"`{new}/`")
        return source

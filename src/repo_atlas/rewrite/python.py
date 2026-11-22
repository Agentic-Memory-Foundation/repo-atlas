"""Update Python imports after files and packages move."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from repo_atlas.rewrite.base import RewriteContext


def _line_starts(source: str) -> list[int]:
    raw = source.encode("utf-8")
    starts = [0]
    for index, byte in enumerate(raw):
        if byte == 10:
            starts.append(index + 1)
    return starts


def _span(source: str, node: ast.AST) -> tuple[int, int]:
    starts = _line_starts(source)
    start = starts[node.lineno - 1] + node.col_offset
    end = starts[node.end_lineno - 1] + node.end_col_offset
    return start, end


def _segment(source: str, node: ast.AST) -> str:
    raw = source.encode("utf-8")
    start, end = _span(source, node)
    return raw[start:end].decode("utf-8")


def _find_module(root: Path, base: Path, module: str | None) -> Path | None:
    parts = module.split(".") if module else []
    candidate = base.joinpath(*parts) if parts else base
    if parts:
        py_file = candidate.with_suffix(".py")
        if (root / py_file).is_file():
            return py_file
    init = candidate / "__init__.py"
    if (root / init).is_file():
        return init
    return None


def resolve_relative(root: Path, importer: Path, level: int, module: str | None) -> Path | None:
    if level <= 0:
        return None
    base = importer.parent
    for _ in range(level - 1):
        if base in {Path("."), Path("")}:
            return None
        base = base.parent
    return _find_module(root, base, module)


def resolve_absolute(root: Path, module: str) -> Path | None:
    if not module:
        return None
    for base in (Path("."), Path("src")):
        found = _find_module(root, base, module)
        if found is not None:
            return found
    return None


def dotted_module(path: Path, *, strip_src: bool) -> str:
    if path.name == "__init__.py":
        parts = list(path.parent.parts)
    else:
        parts = list(path.with_suffix("").parts)
    if strip_src and parts and parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts)


def relative_import(importer: Path, target: Path) -> tuple[int, str | None]:
    """Return (dot count, module) for a relative import of `target` from `importer`."""
    importer_dir = importer.parent.parts
    if target.name == "__init__.py":
        target_parts = target.parent.parts
    else:
        target_parts = target.with_suffix("").parts
    common = 0
    limit = min(len(importer_dir), len(target_parts))
    while common < limit and importer_dir[common] == target_parts[common]:
        common += 1
    ups = len(importer_dir) - common
    rest = target_parts[common:]
    level = ups + 1 if ups else 1
    if not rest:
        return level, None
    return level, ".".join(rest)


def _submodule(root: Path, package_init: Path, name: str) -> Path | None:
    if package_init.name != "__init__.py":
        return None
    package_dir = package_init.parent
    candidate = package_dir / f"{name}.py"
    if (root / candidate).is_file():
        return candidate
    init = package_dir / name / "__init__.py"
    if (root / init).is_file():
        return init
    return None


def _package_dir_for_from(root: Path, importer: Path, node: ast.ImportFrom) -> Path | None:
    if node.level and not node.module:
        base = importer.parent
        for _ in range(node.level - 1):
            if base in {Path("."), Path("")}:
                return None
            base = base.parent
        return base
    return None


def _replace_from_module(segment: str, module_text: str) -> str | None:
    match = re.match(
        r"(?P<indent>\s*)from(?P<space>\s+)(?P<mod>.+?)(?P<imp>\s+import\b)(?P<rest>.*)\Z",
        segment,
        re.DOTALL,
    )
    if not match:
        return None
    return (
        f"{match.group('indent')}from{match.group('space')}{module_text}"
        f"{match.group('imp')}{match.group('rest')}"
    )


def _format_alias(name: str, asname: str | None) -> str:
    if asname:
        return f"{name} as {asname}"
    return name


def _rewrite_from(
    source: str,
    node: ast.ImportFrom,
    importer: Path,
    ctx: RewriteContext,
) -> str | None:
    segment = _segment(source, node)
    if node.level:
        base = resolve_relative(ctx.root, importer, node.level, node.module)
    elif node.module:
        base = resolve_absolute(ctx.root, node.module)
    else:
        return None

    package_dir = _package_dir_for_from(ctx.root, importer, node)
    new_importer = ctx.locate(importer)
    assert new_importer is not None
    changed = new_importer != importer
    submodule_names: dict[str, str] = {}

    if base is not None and base.name == "__init__.py":
        for alias in node.names:
            sub = _submodule(ctx.root, base, alias.name)
            if sub is None:
                continue
            moved = ctx.locate(sub)
            assert moved is not None
            if moved != sub:
                changed = True
                submodule_names[alias.name] = (
                    moved.parent.name if moved.name == "__init__.py" else moved.stem
                )
    elif package_dir is not None:
        init = package_dir / "__init__.py"
        anchor = init if (ctx.root / init).is_file() else None
        for alias in node.names:
            candidate = package_dir / f"{alias.name}.py"
            nested = package_dir / alias.name / "__init__.py"
            sub = candidate if (ctx.root / candidate).is_file() else None
            if sub is None and (ctx.root / nested).is_file():
                sub = nested
            if sub is None:
                continue
            moved = ctx.locate(sub)
            assert moved is not None
            if moved != sub:
                changed = True
                submodule_names[alias.name] = (
                    moved.parent.name if moved.name == "__init__.py" else moved.stem
                )
        if anchor is not None:
            base = anchor

    if base is not None:
        moved_base = ctx.locate(base)
        assert moved_base is not None
        if moved_base != base:
            changed = True
    else:
        moved_base = None

    if not changed or (moved_base is None and not submodule_names):
        return None
    if moved_base is None:
        return None

    if node.level:
        level, module = relative_import(new_importer, moved_base)
        dots = "." * level
        module_text = f"{dots}{module}" if module else dots
    else:
        strip_src = not (node.module or "").startswith("src.")
        module_text = dotted_module(moved_base, strip_src=strip_src)

    if not submodule_names:
        return _replace_from_module(segment, module_text)

    rendered: list[str] = []
    for alias in node.names:
        if alias.name in submodule_names:
            new_name = submodule_names[alias.name]
            if alias.asname:
                rendered.append(f"{new_name} as {alias.asname}")
            elif new_name != alias.name:
                rendered.append(f"{new_name} as {alias.name}")
            else:
                rendered.append(new_name)
        else:
            rendered.append(_format_alias(alias.name, alias.asname))
    indent = re.match(r"\s*", segment).group(0) if segment else ""
    joiner = ",\n    " if "\n" in segment else ", "
    return f"{indent}from {module_text} import {joiner.join(rendered)}"


def _rewrite_import(
    source: str,
    node: ast.Import,
    ctx: RewriteContext,
) -> tuple[str | None, list[tuple[str, str]]]:
    segment = _segment(source, node)
    rendered: list[str] = []
    chains: list[tuple[str, str]] = []
    changed = False
    for alias in node.names:
        target = resolve_absolute(ctx.root, alias.name)
        moved = ctx.locate(target) if target is not None else None
        if target is None or moved is None or moved == target:
            rendered.append(_format_alias(alias.name, alias.asname))
            continue
        changed = True
        strip_src = not alias.name.startswith("src.")
        new_dotted = dotted_module(moved, strip_src=strip_src)
        if alias.asname:
            rendered.append(f"{new_dotted} as {alias.asname}")
        elif "." not in alias.name:
            if new_dotted == alias.name:
                rendered.append(new_dotted)
            else:
                rendered.append(f"{new_dotted} as {alias.name}")
        else:
            old_root = alias.name.split(".", 1)[0]
            new_root = new_dotted.split(".", 1)[0]
            if old_root == new_root:
                rendered.append(new_dotted)
                chains.append((alias.name, new_dotted))
            else:
                rendered.append(f"{new_dotted} as {old_root}")
    if not changed:
        return None, []
    indent = re.match(r"\s*", segment).group(0) if segment else ""
    return f"{indent}import {', '.join(rendered)}", chains


def _dotted_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    current: ast.AST | None = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _replace_chains(source: str, chains: list[tuple[str, str]]) -> str:
    if not chains:
        return source
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    wanted = dict(chains)
    matches: list[tuple[int, ast.AST, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        dotted = _dotted_name(node)
        if dotted in wanted:
            matches.append((len(dotted or ""), node, wanted[dotted]))
    matches.sort(key=lambda item: item[0], reverse=True)
    raw = source.encode("utf-8")
    consumed: list[tuple[int, int]] = []
    edits: list[tuple[int, int, bytes]] = []
    for _length, node, new in matches:
        start, end = _span(source, node)
        if any(start >= left and end <= right for left, right in consumed):
            continue
        consumed.append((start, end))
        edits.append((start, end, new.encode("utf-8")))
    for start, end, new in sorted(edits, key=lambda item: item[0], reverse=True):
        raw = raw[:start] + new + raw[end:]
    return raw.decode("utf-8")


class PythonRewriter:
    """Rewrite `import` and `from ... import` statements that point at moved modules."""

    def handles(self, path: Path) -> bool:
        return path.suffix == ".py"

    def rewrite(self, source: str, path: Path, ctx: RewriteContext) -> str:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return source
        raw = source.encode("utf-8")
        edits: list[tuple[int, int, bytes]] = []
        chains: list[tuple[str, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                updated = _rewrite_from(source, node, path, ctx)
                if updated is not None and updated != _segment(source, node):
                    start, end = _span(source, node)
                    edits.append((start, end, updated.encode("utf-8")))
            elif isinstance(node, ast.Import):
                updated, extra = _rewrite_import(source, node, ctx)
                if updated is not None and updated != _segment(source, node):
                    start, end = _span(source, node)
                    edits.append((start, end, updated.encode("utf-8")))
                    chains.extend(extra)
        if not edits and not chains:
            return source
        for start, end, new in sorted(edits, key=lambda item: item[0], reverse=True):
            raw = raw[:start] + new + raw[end:]
        updated_source = raw.decode("utf-8")
        return _replace_chains(updated_source, chains)

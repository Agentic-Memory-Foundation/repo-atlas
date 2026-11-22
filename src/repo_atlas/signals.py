"""Extract symbols, docstrings, comments, and imports from a source file."""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".java": "java",
    ".md": "markdown",
    ".mdx": "markdown",
    ".rst": "rst",
}

_JS_FUNC = re.compile(
    r"(?P<export>export\s+)?(?P<default>default\s+)?(?:async\s+)?function\s+\*?\s*"
    r"(?P<name>[A-Za-z_$][\w$]*)"
)
_JS_CLASS = re.compile(
    r"(?P<export>export\s+)?(?P<default>default\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)"
)
_JS_CONST = re.compile(
    r"(?P<export>export\s+)?(?P<default>default\s+)?(?:const|let|var)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*="
)
_JS_EXPORT_LIST = re.compile(r"export\s*\{([^}]+)\}")
_JSDOC = re.compile(r"^\s*/\*\*(.*?)\*/", re.DOTALL)
_BLOCK_COMMENT = re.compile(r"/\*(.*?)\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"//\s?(.*)")
_GO_FUNC = re.compile(r"^func\s+(?:\([^)\n]*\)\s*)?(?P<name>[A-Za-z_]\w*)", re.MULTILINE)
_RUST_FN = re.compile(
    r"^\s*(?P<pub>pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+(?P<name>[A-Za-z_]\w*)",
    re.MULTILINE,
)
_RUBY_DEF = re.compile(r"^\s*def\s+(?:self\.)?(?P<name>[A-Za-z_]\w*)", re.MULTILINE)
_JAVA_METHOD = re.compile(
    r"^\s*(?:public|protected|private)?\s*(?:static\s+)?[\w<>\[\]]+\s+(?P<name>[A-Za-z_]\w*)\s*\(",
    re.MULTILINE,
)


@dataclass
class Symbol:
    name: str
    kind: str
    exported: bool
    docstring: str = ""
    line: int = 1


@dataclass
class FileSignals:
    path: Path
    language: str
    stem: str
    suffix: str
    docstring: str = ""
    comments: list[str] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    excerpt: str = ""
    text: str = ""

    def to_summary(self) -> dict[str, object]:
        return {
            "language": self.language,
            "docstring": self.docstring[:400],
            "symbols": [
                {"name": symbol.name, "kind": symbol.kind, "exported": symbol.exported}
                for symbol in self.symbols[:16]
            ],
            "imports": self.imports[:16],
            "comments": self.comments[:8],
            "excerpt": self.excerpt[:800],
        }


def language_for(path: Path) -> str | None:
    return LANGUAGE_BY_SUFFIX.get(path.suffix.lower())


def _clean_comment(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip().lstrip("*").strip()
        if stripped:
            lines.append(stripped)
    return " ".join(lines).strip()


def _excerpt(source: str, limit: int = 1200) -> str:
    snippet = source.strip()
    if len(snippet) <= limit:
        return snippet
    return snippet[:limit]


def extract_signals(path: Path, source: str) -> FileSignals:
    """Extract whatever the file's language makes cheap and reliable."""
    language = language_for(path) or "text"
    signals = FileSignals(
        path=path,
        language=language,
        stem=path.stem,
        suffix=path.suffix,
        excerpt=_excerpt(source),
        text=source,
    )
    if language == "python":
        _extract_python(source, signals)
    elif language in {"javascript", "typescript"}:
        _extract_javascript(source, signals)
    elif language == "go":
        _extract_pattern(_GO_FUNC, source, signals, exported_group="name")
    elif language == "rust":
        _extract_rust(source, signals)
    elif language == "ruby":
        _extract_pattern(_RUBY_DEF, source, signals)
    elif language == "java":
        _extract_pattern(_JAVA_METHOD, source, signals)
    elif language == "markdown":
        _extract_markdown(source, signals)
    else:
        signals.comments = _generic_comments(source)
    if not signals.docstring and signals.comments:
        signals.docstring = signals.comments[0][:400]
    return signals


def _extract_python(source: str, signals: FileSignals) -> None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        signals.comments = _generic_comments(source)
        return
    signals.docstring = ast.get_docstring(tree) or ""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            signals.symbols.append(
                Symbol(
                    name=node.name,
                    kind="function",
                    exported=not node.name.startswith("_"),
                    docstring=ast.get_docstring(node) or "",
                    line=node.lineno,
                )
            )
        elif isinstance(node, ast.ClassDef):
            signals.symbols.append(
                Symbol(
                    name=node.name,
                    kind="class",
                    exported=not node.name.startswith("_"),
                    docstring=ast.get_docstring(node) or "",
                    line=node.lineno,
                )
            )
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    signals.symbols.append(
                        Symbol(name=target.id, kind="const", exported=True, line=node.lineno)
                    )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id.isupper():
                signals.symbols.append(
                    Symbol(
                        name=node.target.id,
                        kind="const",
                        exported=True,
                        line=node.lineno,
                    )
                )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                signals.imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            signals.imports.append(module)
    signals.exports = [symbol.name for symbol in signals.symbols if symbol.exported]
    signals.comments = _python_comments(source)


def _python_comments(source: str) -> list[str]:
    comments: list[str] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type == tokenize.COMMENT:
                text = token.string.lstrip("#").strip()
                if text and not text.startswith("!"):
                    comments.append(text)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return _generic_comments(source)
    return comments[:40]


def _extract_javascript(source: str, signals: FileSignals) -> None:
    exported_names: set[str] = set()
    for match in _JS_EXPORT_LIST.finditer(source):
        for part in match.group(1).split(","):
            name = part.strip().split(" as ")[-1].strip()
            name = name.split(" as ")[0].strip()
            piece = part.replace(" as ", " ").split()
            if piece:
                exported_names.add(piece[0])
            if name:
                exported_names.add(name)
    doc = _JSDOC.search(source)
    if doc and doc.start() < 400:
        signals.docstring = _clean_comment(doc.group(1))
    for match in _JS_FUNC.finditer(source):
        name = match.group("name")
        exported = bool(match.group("export")) or name in exported_names
        signals.symbols.append(Symbol(name=name, kind="function", exported=exported))
    for match in _JS_CLASS.finditer(source):
        name = match.group("name")
        exported = bool(match.group("export")) or name in exported_names
        signals.symbols.append(Symbol(name=name, kind="class", exported=exported))
    for match in _JS_CONST.finditer(source):
        name = match.group("name")
        if any(symbol.name == name for symbol in signals.symbols):
            continue
        exported = bool(match.group("export")) or name in exported_names
        signals.symbols.append(Symbol(name=name, kind="const", exported=exported))
    import_re = re.compile(
        r"""(?:import\s+(?:[^'";]+?\s+from\s+)?|export\s+[^'";]+?\s+from\s+|require\s*\(\s*)"""
        r"""(?P<q>['\"])(?P<spec>[^'\"]+)(?P=q)"""
    )
    signals.imports = [match.group("spec") for match in import_re.finditer(source)]
    signals.exports = [symbol.name for symbol in signals.symbols if symbol.exported]
    signals.comments = _js_comments(source)
    if not signals.docstring and signals.comments:
        signals.docstring = signals.comments[0]


def _js_comments(source: str) -> list[str]:
    comments: list[str] = []
    for match in _BLOCK_COMMENT.finditer(source):
        text = _clean_comment(match.group(1))
        if text:
            comments.append(text)
    for match in _LINE_COMMENT.finditer(source):
        text = match.group(1).strip()
        if text:
            comments.append(text)
    return comments[:40]


def _extract_pattern(
    pattern: re.Pattern[str],
    source: str,
    signals: FileSignals,
    exported_group: str | None = None,
) -> None:
    for match in pattern.finditer(source):
        name = match.group("name")
        if name in {"if", "for", "while", "switch", "catch"}:
            continue
        exported = True
        if exported_group and "pub" in match.groupdict():
            exported = bool(match.group("pub"))
        signals.symbols.append(Symbol(name=name, kind="function", exported=exported))
    signals.exports = [symbol.name for symbol in signals.symbols if symbol.exported]
    signals.comments = _generic_comments(source)
    if signals.comments and not signals.docstring:
        signals.docstring = signals.comments[0]


def _extract_rust(source: str, signals: FileSignals) -> None:
    _extract_pattern(_RUST_FN, source, signals, exported_group="pub")
    for match in re.finditer(
        r"^\s*(?P<pub>pub(?:\([^)]*\))?\s+)?struct\s+(?P<name>[A-Za-z_]\w*)",
        source,
        re.MULTILINE,
    ):
        signals.symbols.append(
            Symbol(
                name=match.group("name"),
                kind="class",
                exported=bool(match.group("pub")),
            )
        )


def _extract_markdown(source: str, signals: FileSignals) -> None:
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            if title:
                signals.docstring = title
                break
    signals.comments = []


def _generic_comments(source: str) -> list[str]:
    comments: list[str] = []
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            text = stripped.lstrip("#").strip()
            if text:
                comments.append(text)
        elif stripped.startswith("//"):
            text = stripped.lstrip("/").strip()
            if text:
                comments.append(text)
    return comments[:40]

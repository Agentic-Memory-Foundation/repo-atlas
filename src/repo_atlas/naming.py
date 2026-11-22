"""File and directory name rules."""

from __future__ import annotations

import keyword
import re

GENERIC_STEMS = frozenset(
    {
        "utils",
        "util",
        "helpers",
        "helper",
        "misc",
        "stuff",
        "tmp",
        "temp",
        "common",
        "shared",
        "lib",
        "libs",
        "data",
        "file",
        "files",
        "module",
        "modules",
        "functions",
        "func",
        "funcs",
        "code",
        "manager",
        "handler",
        "handlers",
        "processor",
        "service",
        "services",
        "controller",
        "logic",
        "base",
        "general",
        "default",
        "example",
        "sample",
        "demo",
        "output",
        "input",
        "result",
        "results",
        "item",
        "items",
        "obj",
        "object",
        "thing",
        "things",
        "foo",
        "bar",
        "baz",
        "other",
        "various",
        "extra",
        "extras",
        "script",
        "scripts",
        "my",
        "our",
        "core",
        "impl",
        "implementation",
        "custom",
        "wrapper",
        "wrappers",
        "client",
        "clients",
        "internal",
        "old",
        "new",
        "backup",
        "dump",
        "wip",
        "scratch",
        "todo",
        "notes",
        "note",
        "mod",
        "inc",
        "include",
        "src",
        "app",
        "main",
        "index",
        "test",
        "tests",
    }
)

GENERIC_SYMBOLS = frozenset(
    {
        "main",
        "run",
        "setup",
        "init",
        "helper",
        "util",
        "utils",
        "process",
        "handle",
        "handler",
        "execute",
        "start",
        "foo",
        "bar",
        "baz",
        "func",
        "function",
        "do_stuff",
        "process_data",
        "do_thing",
        "wrapper",
        "call",
        "calls",
    }
)

# Tokens that make poor directory names even when they are shared.
DIRECTORY_STOPWORDS = frozenset(
    {
        "this",
        "that",
        "with",
        "from",
        "into",
        "using",
        "used",
        "based",
        "given",
        "return",
        "returns",
        "returned",
        "value",
        "values",
        "string",
        "text",
        "line",
        "lines",
        "row",
        "rows",
        "column",
        "columns",
        "number",
        "numbers",
        "count",
        "name",
        "names",
        "path",
        "paths",
        "error",
        "errors",
        "status",
        "type",
        "types",
        "object",
        "objects",
        "method",
        "methods",
        "function",
        "functions",
        "class",
        "classes",
        "module",
        "modules",
        "file",
        "files",
        "code",
        "data",
        "info",
        "item",
        "items",
        "result",
        "results",
        "input",
        "output",
        "true",
        "false",
        "none",
        "null",
        "args",
        "kwargs",
        "param",
        "parameter",
        "across",
        "exported",
        "system",
        "helper",
        "helpers",
        "utility",
        "utilities",
        "common",
        "shared",
        "internal",
        "public",
        "private",
        "default",
        "current",
        "other",
        "various",
        "extra",
        "local",
        "global",
        "simple",
        "basic",
        "main",
        "test",
        "tests",
        "when",
        "where",
        "what",
        "which",
        "their",
        "there",
        "these",
        "those",
        "after",
        "before",
        "about",
        "should",
        "would",
        "could",
        "every",
        "each",
        "only",
        "also",
        "just",
        "than",
        "then",
        "them",
        "they",
        "have",
        "been",
        "will",
        "your",
        "over",
        "under",
        "does",
        "done",
        "make",
        "made",
        "some",
    }
)

TEXT_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "are",
        "but",
        "not",
        "you",
        "all",
        "can",
        "her",
        "was",
        "one",
        "our",
        "out",
        "get",
        "use",
        "how",
        "its",
        "this",
        "that",
        "with",
        "from",
        "into",
        "using",
        "used",
        "return",
        "returns",
        "true",
        "false",
        "none",
        "null",
        "self",
        "cls",
        "args",
        "kwargs",
        "when",
        "where",
        "what",
        "which",
        "their",
        "there",
        "these",
        "those",
        "after",
        "before",
        "about",
        "should",
        "would",
        "could",
        "every",
        "each",
        "only",
        "also",
        "just",
        "than",
        "then",
        "them",
        "they",
        "have",
        "been",
        "will",
        "your",
        "over",
        "under",
        "does",
        "done",
        "some",
        "any",
        "via",
        "per",
        "within",
        "without",
        "across",
        "module",
        "function",
        "class",
        "method",
        "param",
        "parameter",
        "type",
        "value",
        "values",
        "string",
        "object",
        "def",
        "async",
        "await",
        "const",
        "var",
        "let",
        "import",
        "export",
        "public",
        "private",
        "protected",
        "static",
        "void",
        "int",
        "str",
        "bool",
        "float",
        "dict",
        "list",
        "set",
        "tuple",
        "optional",
        "bytes",
    }
)

MAX_STEM_LENGTH = 60

_CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
_ACRONYM_BOUNDARY = re.compile(r"([A-Z]+)([A-Z][a-z])")


def split_identifier(name: str) -> list[str]:
    """Split a file stem or symbol into lowercase tokens."""
    text = name.replace("-", "_").replace(".", "_")
    text = re.sub(r"([A-Za-z])(\d)", r"\1_\2", text)
    text = re.sub(r"(\d)([A-Za-z])", r"\1_\2", text)
    text = _CAMEL_BOUNDARY.sub(r"\1_\2", text)
    text = _ACRONYM_BOUNDARY.sub(r"\1_\2", text)
    parts = re.split(r"[^A-Za-z0-9]+", text)
    return [part.lower() for part in parts if part]


def is_generic_token(token: str) -> bool:
    return token.lower() in GENERIC_STEMS or token.lower() in TEXT_STOPWORDS


def is_generic_stem(stem: str) -> bool:
    """Return True when a file stem does not say what the file does."""
    raw = stem.strip().lower()
    if not raw or raw in GENERIC_STEMS or len(raw) <= 2:
        return True
    parts = [part for part in split_identifier(raw) if part and not part.isdigit()]
    if not parts:
        return True
    return all(part in GENERIC_STEMS for part in parts)


def is_generic_dirname(name: str) -> bool:
    return is_generic_stem(name)


def is_generic_symbol(name: str) -> bool:
    parts = [part for part in split_identifier(name) if not part.isdigit()]
    if not parts:
        return True
    if name.lower() in GENERIC_SYMBOLS:
        return True
    return all(part in GENERIC_STEMS or part in GENERIC_SYMBOLS for part in parts)


def naming_style_for(language: str | None, configured: str) -> str:
    """Python modules are always snake_case. Other languages follow config."""
    if language == "python":
        return "snake"
    if configured and configured != "auto":
        return configured
    if language in {"javascript", "typescript"}:
        return "kebab"
    return "snake"


def join_tokens(tokens: list[str], style: str) -> str:
    cleaned: list[str] = []
    for token in tokens:
        text = re.sub(r"[^a-z0-9]", "", token.lower())
        if not text or text.isdigit():
            continue
        cleaned.append(text)
    if not cleaned:
        return ""
    if style == "kebab":
        return "-".join(cleaned)
    if style == "camel":
        head, *tail = cleaned
        return head + "".join(part[:1].upper() + part[1:] for part in tail)
    return "_".join(cleaned)


def trim_tokens(tokens: list[str], style: str) -> list[str]:
    current = list(tokens)
    while current and len(join_tokens(current, style)) > MAX_STEM_LENGTH:
        if len(current) == 1:
            stem = join_tokens(current, style)[:MAX_STEM_LENGTH].strip("_-")
            return [stem] if stem else []
        current = current[:-1]
    return current


def valid_stem(stem: str, language: str | None, style: str | None = None) -> bool:
    if not stem or stem.startswith((".", "_")) or stem.endswith((".", "_", "-")):
        return False
    resolved = style or naming_style_for(language, "auto")
    if language == "python" or resolved == "snake":
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", stem):
            return False
        if keyword.iskeyword(stem):
            return False
        return True
    if resolved == "kebab":
        return re.fullmatch(r"[a-z][a-z0-9-]*", stem) is not None
    if resolved == "camel":
        return re.fullmatch(r"[a-z][A-Za-z0-9]*", stem) is not None
    return re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", stem) is not None


def avoid_keyword(stem: str, language: str | None) -> str:
    if language == "python" and keyword.iskeyword(stem):
        return f"{stem}_mod"
    return stem


def build_filename(
    tokens: list[str],
    suffix: str,
    language: str | None,
    configured_style: str,
) -> str | None:
    """Build a basename from tokens, or return None when the name is invalid."""
    style = naming_style_for(language, configured_style)
    trimmed = trim_tokens(tokens, style)
    stem = avoid_keyword(join_tokens(trimmed, style), language)
    if not valid_stem(stem, language, style):
        return None
    if suffix and not suffix.startswith("."):
        suffix = "." + suffix
    return f"{stem}{suffix}"


def valid_directory_name(name: str, contains_python: bool) -> bool:
    if contains_python:
        return valid_stem(name, "python", "snake") and not keyword.iskeyword(name)
    return valid_stem(name, None, "kebab") or valid_stem(name, None, "snake")


def directory_token_ok(token: str) -> bool:
    text = token.lower()
    if len(text) < 4:
        return False
    if text in DIRECTORY_STOPWORDS or text in GENERIC_STEMS or text in TEXT_STOPWORDS:
        return False
    if not text.isalpha():
        return False
    return True


def humanize(name: str) -> str:
    """Turn a symbol or stem into a short feature title."""
    parts = split_identifier(name)
    if not parts:
        return name
    words = " ".join(parts)
    return words[:1].upper() + words[1:]


def first_sentence(text: str, limit: int = 90) -> str:
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return ""
    match = re.match(r"^(.+?[.!?])(?:\s|$)", cleaned)
    sentence = match.group(1) if match else cleaned
    sentence = sentence.rstrip(".")
    if len(sentence) > limit:
        sentence = sentence[: limit - 3].rstrip() + "..."
    return sentence

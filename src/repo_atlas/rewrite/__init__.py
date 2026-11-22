"""Language-specific reference updates. Register more rewriters for other stacks."""

from __future__ import annotations

from repo_atlas.rewrite.base import (
    ImportRewriter,
    RewriteContext,
    get_rewriters,
    register_rewriter,
    rewrite_source,
)
from repo_atlas.rewrite.javascript import JavaScriptRewriter
from repo_atlas.rewrite.markdown import MarkdownRewriter
from repo_atlas.rewrite.python import PythonRewriter

register_rewriter(PythonRewriter())
register_rewriter(JavaScriptRewriter())
register_rewriter(MarkdownRewriter())

__all__ = [
    "ImportRewriter",
    "RewriteContext",
    "get_rewriters",
    "register_rewriter",
    "rewrite_source",
]

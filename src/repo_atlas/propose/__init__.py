"""Rename proposal backends."""

from __future__ import annotations

from repo_atlas.propose.agent import build_agent_pack, ingest_agent_plan
from repo_atlas.propose.heuristic import propose_heuristic
from repo_atlas.propose.llm import propose_llm

__all__ = [
    "build_agent_pack",
    "ingest_agent_plan",
    "propose_heuristic",
    "propose_llm",
]

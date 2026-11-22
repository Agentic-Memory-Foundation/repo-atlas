"""Name-only retrieval metrics for the repo-atlas benchmark.

The scorer is intentionally simple and fully deterministic.

* Tokens are lowercase words split on punctuation, underscores, hyphens, and camel case.
* A short stop list drops question words ("where", "is", "the", "code", ...).
* Matching uses a light stemmer: ``signatures`` matches ``signature``, ``verifies`` matches
  ``verify``, ``formatted`` matches ``format``, and ``applied`` matches ``apply``.
* hit@k ranks files by the sum of IDF weights of task tokens that match the path.
  A file with score 0 is a miss even if the repository is small.
* The simulated agent issues one glob per stemmed keyword, longest first, then pairwise
  globs of the three longest needles, then one content grep. A glob counts as a find
  when the target path is in the result and the result has 1 to 5 files.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from itertools import combinations
from pathlib import Path

from repo_atlas.naming import split_identifier

STOPWORDS = frozenset(
    {
        "where",
        "is",
        "the",
        "code",
        "that",
        "a",
        "an",
        "of",
        "for",
        "to",
        "in",
        "on",
        "are",
        "does",
        "do",
        "how",
        "file",
        "files",
        "function",
        "find",
        "which",
        "what",
        "when",
        "with",
        "from",
        "into",
        "and",
        "or",
        "it",
        "its",
        "by",
        "at",
        "as",
        "be",
        "this",
        "there",
        "located",
        "implementation",
        "implement",
        "inside",
        "lives",
        "live",
        "using",
        "used",
        "through",
        "across",
    }
)

_FEATURE = re.compile(r"^- `([^`]+)`: (.+?)\s*$")


def tokenize(text: str) -> list[str]:
    normalized = re.sub(r"[/_.\\-]+", " ", text)
    tokens: list[str] = []
    for piece in normalized.split():
        for part in split_identifier(piece):
            if part in STOPWORDS or len(part) <= 1 or part.isdigit():
                continue
            tokens.append(part)
    return tokens


def primary_needle(keyword: str) -> str | None:
    """Stem one task word into the glob fragment a simple agent would type."""
    text = keyword.lower()
    original = text
    if (len(text) > 4 and text.endswith("ies")) or (len(text) > 4 and text.endswith("ied")):
        text = text[:-3] + "y"
    elif len(text) > 5 and text.endswith("ing"):
        text = text[:-3]
        if len(text) >= 2 and text[-1] == text[-2] and text[-1] not in "aeiou":
            text = text[:-1]
    elif len(text) > 4 and text.endswith("ed"):
        text = text[:-2]
        if len(text) >= 2 and text[-1] == text[-2] and text[-1] not in "aeiou":
            text = text[:-1]
    elif len(text) > 3 and text.endswith("s") and not text.endswith("ss"):
        text = text[:-1]
    if len(text) >= 4:
        return text
    if len(original) >= 4:
        return original
    return None


def token_forms(token: str) -> set[str]:
    forms = {token.lower()}
    needle = primary_needle(token)
    if needle:
        forms.add(needle)
    return {form for form in forms if len(form) >= 3}


def forms_match(left: str, right: str) -> bool:
    left_forms = token_forms(left)
    right_forms = token_forms(right)
    if left_forms & right_forms:
        return True
    for alpha in left_forms:
        for beta in right_forms:
            short, long = (alpha, beta) if len(alpha) <= len(beta) else (beta, alpha)
            if len(short) >= 4 and long.startswith(short):
                return True
    return False


def idf_map(paths: list[str]) -> dict[str, float]:
    documents = [set(tokenize(path)) for path in paths]
    counts: Counter[str] = Counter()
    for document in documents:
        counts.update(document)
    total = max(len(documents), 1)
    return {token: math.log((total + 1) / (count + 1)) + 1.0 for token, count in counts.items()}


def score_path(question: str, path: str, idf: dict[str, float]) -> float:
    path_tokens = tokenize(path)
    score = 0.0
    seen: set[str] = set()
    for keyword in tokenize(question):
        if keyword in seen:
            continue
        matched = [token for token in path_tokens if forms_match(keyword, token)]
        if not matched:
            continue
        seen.add(keyword)
        score += max(idf.get(token, 1.0) for token in matched)
    return score


def rank_paths(question: str, paths: list[str], idf: dict[str, float] | None = None) -> list[str]:
    weights = idf if idf is not None else idf_map(paths)
    scored = [(score_path(question, path, weights), path) for path in paths]
    positive = [item for item in scored if item[0] > 0]
    positive.sort(key=lambda item: (-item[0], item[1]))
    return [path for _score, path in positive]


def hit_at(ranked: list[str], target: str, k: int) -> bool:
    try:
        return ranked.index(target) < k
    except ValueError:
        return False


def _needles(question: str) -> list[str]:
    needles: list[str] = []
    for keyword in tokenize(question):
        needle = primary_needle(keyword)
        if needle and needle not in needles:
            needles.append(needle)
    needles.sort(key=lambda item: (-len(item), item))
    return needles


def simulate_agent(
    question: str, paths: list[str], target: str, target_text: str
) -> dict[str, object]:
    """Count glob and grep calls until a simple agent would see the target."""
    needles = _needles(question)
    calls = 0
    for needle in needles:
        calls += 1
        matches = [path for path in paths if needle in path.lower()]
        if target in matches and 1 <= len(matches) <= 5:
            return {
                "calls": calls,
                "found_by": "glob",
                "hit": True,
                "needle": needle,
                "match_count": len(matches),
            }
    for left, right in combinations(needles[:3], 2):
        calls += 1
        matches = [path for path in paths if left in path.lower() and right in path.lower()]
        if target in matches and 1 <= len(matches) <= 5:
            return {
                "calls": calls,
                "found_by": "glob",
                "hit": True,
                "needle": f"{left}+{right}",
                "match_count": len(matches),
            }
    if needles:
        calls += 1
        longest = max(needles, key=len)
        if longest.lower() in target_text.lower():
            return {
                "calls": calls,
                "found_by": "grep",
                "hit": True,
                "needle": longest,
                "match_count": None,
            }
    return {"calls": calls, "found_by": None, "hit": False, "needle": None, "match_count": None}


def parse_features(markdown: str) -> list[dict[str, str]]:
    """Read feature rows from a repo-atlas managed section. Directory guide rows are skipped."""
    start = markdown.find("<!-- repo-atlas:start -->")
    end = markdown.find("<!-- repo-atlas:end -->")
    body = markdown[start:end] if start != -1 and end > start else markdown
    features: list[dict[str, str]] = []
    for line in body.splitlines():
        match = _FEATURE.match(line.strip())
        if not match:
            continue
        path, description = match.group(1), match.group(2)
        if path.endswith("/") or not Path(path).suffix:
            continue
        features.append({"path": path, "description": description})
    return features


def map_locates(question: str, features: list[dict[str, str]], target: str) -> bool:
    """True when the best feature description (ties allowed) lists the target path."""
    best = 0
    winners: list[dict[str, str]] = []
    for feature in features:
        description_tokens = tokenize(feature["description"])
        score = 0
        seen: set[str] = set()
        for keyword in tokenize(question):
            if keyword in seen:
                continue
            if any(forms_match(keyword, token) for token in description_tokens):
                seen.add(keyword)
                score += 1
        if score > best:
            best = score
            winners = [feature]
        elif score == best and score > 0:
            winners.append(feature)
    if best <= 0:
        return False
    return any(feature["path"] == target for feature in winners)

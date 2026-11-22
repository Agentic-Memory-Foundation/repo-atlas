"""Deterministic rename proposals from symbols, docstrings, and TF-IDF keywords."""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

from repo_atlas.config import Config
from repo_atlas.naming import (
    build_filename,
    directory_token_ok,
    is_generic_dirname,
    is_generic_stem,
    is_generic_symbol,
    is_generic_token,
    split_identifier,
    valid_directory_name,
)
from repo_atlas.plan import PLAN_VERSION, PlanItem, RenamePlan
from repo_atlas.protect import Protection
from repo_atlas.scan import RepoIndex
from repo_atlas.signals import FileSignals

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]+")


def _text_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for match in _WORD.finditer(text or ""):
        for part in split_identifier(match.group(0)):
            if len(part) < 3 or is_generic_token(part):
                continue
            tokens.append(part)
    return tokens


def _file_tokens(signals: FileSignals) -> list[str]:
    chunks = [signals.docstring, *signals.comments]
    for symbol in signals.symbols:
        chunks.append(symbol.name)
        chunks.append(symbol.docstring)
    return _text_tokens(" ".join(chunks))


def _idf(files: list[FileSignals]) -> dict[str, float]:
    docs = [set(_file_tokens(item)) for item in files]
    df: Counter[str] = Counter()
    for doc in docs:
        df.update(doc)
    total = max(len(docs), 1)
    return {token: math.log((total + 1) / (count + 1)) + 1.0 for token, count in df.items()}


def _keyword_phrase(signals: FileSignals, idf: dict[str, float], limit: int = 4) -> list[str]:
    tokens = _file_tokens(signals)
    counts = Counter(tokens)
    first_pos: dict[str, int] = {}
    for index, token in enumerate(tokens):
        first_pos.setdefault(token, index)
    ranked = sorted(
        counts,
        key=lambda token: (
            -(counts[token] * idf.get(token, 1.0)),
            first_pos[token],
            token,
        ),
    )
    return ranked[:limit]


def _symbol_pool(signals: FileSignals) -> list:
    specific = [
        symbol
        for symbol in signals.symbols
        if not symbol.name.startswith("_") and not is_generic_symbol(symbol.name)
    ]
    functions = [symbol for symbol in specific if symbol.kind in {"function", "class"}]
    pool = functions or specific
    exported = [symbol for symbol in pool if symbol.exported]
    return exported or pool


def _score_symbol(symbol, signals: FileSignals, idf: dict[str, float]) -> float:
    tokens = [token for token in split_identifier(symbol.name) if not is_generic_token(token)]
    doc = set(_text_tokens(signals.docstring))
    overlap = sum(2.0 for token in tokens if token in doc)
    distinct = sum(idf.get(token, 1.0) for token in tokens)
    bonus = 0.35 if symbol.exported else 0.0
    if symbol.kind == "class":
        bonus += 0.15
    return overlap + distinct + bonus


def _propose_file(
    signals: FileSignals,
    idf: dict[str, float],
    config: Config,
    protection: Protection,
) -> tuple[PlanItem | None, dict[str, str] | None]:
    path = signals.path
    protected = protection.reason(path)
    if protected:
        if is_generic_stem(signals.stem):
            return None, {"path": path.as_posix(), "reason": protected}
        return None, None
    if signals.language in {"markdown", "rst", "text"} and not signals.symbols:
        # Markdown keeps its name unless the stem is generic and a title is specific.
        if not is_generic_stem(signals.stem):
            return None, None
    if not is_generic_stem(signals.stem):
        return None, None

    pool = _symbol_pool(signals)
    reason = ""
    confidence = 0.0
    tokens: list[str] = []
    if len(pool) == 1:
        tokens = split_identifier(pool[0].name)
        reason = f"Single public symbol {pool[0].name}."
        confidence = 0.91
    elif len(pool) > 1:
        ranked = sorted(
            pool,
            key=lambda symbol: (
                -_score_symbol(symbol, signals, idf),
                -len(symbol.name),
                symbol.name,
            ),
        )
        winner = ranked[0]
        tokens = split_identifier(winner.name)
        reason = f"Most distinctive public symbol {winner.name} among {len(pool)}."
        doc_tokens = set(_text_tokens(signals.docstring))
        if any(token in doc_tokens for token in tokens):
            confidence = 0.78
        else:
            confidence = 0.64
    else:
        tokens = _keyword_phrase(signals, idf)
        if tokens:
            reason = "Keywords from the file text: " + ", ".join(tokens) + "."
            confidence = 0.58 if len(tokens) >= 2 else 0.52

    if confidence < config.min_confidence or not tokens:
        return None, {
            "path": path.as_posix(),
            "reason": "no specific name cleared the confidence threshold",
        }

    filename = build_filename(tokens, signals.suffix, signals.language, config.naming_style)
    if filename is None or filename == path.name:
        return None, {"path": path.as_posix(), "reason": "proposed name was invalid or unchanged"}

    extras = [token for token in _keyword_phrase(signals, idf, limit=6) if token not in tokens]
    item = PlanItem(
        path=path.as_posix(),
        kind="file",
        language=signals.language,
        current_name=path.name,
        proposed_name=filename,
        proposed_path=path.as_posix(),
        reason=reason,
        confidence=round(confidence, 2),
        signals=signals.to_summary(),
        extra_tokens=extras[:4],
    )
    return item, None


def _child_token_set(signals: FileSignals, proposal: PlanItem | None) -> set[str]:
    tokens: set[str] = set()
    if proposal is not None:
        tokens.update(split_identifier(Path(proposal.proposed_name).stem))
    else:
        tokens.update(split_identifier(signals.stem))
    tokens.update(_text_tokens(signals.docstring))
    for symbol in signals.symbols:
        tokens.update(split_identifier(symbol.name))
        tokens.update(_text_tokens(symbol.docstring))
    return {token for token in tokens if directory_token_ok(token)}


def _propose_directories(
    index: RepoIndex,
    file_items: dict[Path, PlanItem],
    idf: dict[str, float],
    config: Config,
    protection: Protection,
) -> list[PlanItem]:
    code_files = [
        item
        for item in index.files
        if item.language not in {"markdown", "rst", "text"} and item.suffix
    ]
    directories: set[Path] = set()
    for signals in code_files:
        parent = signals.path.parent
        while parent != Path("."):
            directories.add(parent)
            parent = parent.parent

    proposals: list[PlanItem] = []
    for directory in sorted(directories, key=lambda item: item.as_posix()):
        if protection.is_structural_dir(directory) or protection.is_protected(directory):
            continue
        if not is_generic_dirname(directory.name):
            continue
        children = [signals for signals in code_files if directory in signals.path.parents]
        if len(children) < 2:
            continue
        per_child = [
            _child_token_set(signals, file_items.get(signals.path)) for signals in children
        ]
        counts: Counter[str] = Counter()
        for tokens in per_child:
            counts.update(tokens)
        total = len(children)
        contains_python = any(signals.language == "python" for signals in children)
        ranked = []
        for token, hits in counts.items():
            coverage = hits / total
            if hits < 2 or coverage < 0.6:
                continue
            if not valid_directory_name(token, contains_python):
                continue
            ranked.append((coverage, idf.get(token, 1.0), len(token), token, hits))
        if not ranked:
            continue
        ranked.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))
        _coverage, _idf_score, _length, token, hits = ranked[0]
        if token == directory.name:
            continue
        confidence = round(0.5 + 0.4 * (hits / total), 2)
        if confidence < config.min_confidence:
            continue
        proposals.append(
            PlanItem(
                path=directory.as_posix(),
                kind="directory",
                language="python" if contains_python else None,
                current_name=directory.name,
                proposed_name=token,
                proposed_path=directory.as_posix(),
                reason=f"Shared token {token} appears in {hits} of {total} files.",
                confidence=confidence,
                signals=None,
                extra_tokens=[item[3] for item in ranked[1:4]],
            )
        )
    return proposals


def _relocate(path: Path, dir_names: dict[Path, str], file_names: dict[Path, str]) -> Path:
    original = Path()
    parts: list[str] = []
    raw_parts = list(path.parts)
    for index, part in enumerate(raw_parts):
        original = original / part
        last = index == len(raw_parts) - 1
        if last and path in file_names:
            parts.append(file_names[path])
        elif original in dir_names and (not last or path not in file_names):
            parts.append(dir_names[original])
        else:
            parts.append(part)
    return Path(*parts)


def _taken_stems(dest_dir: Path, owners: dict[Path, Path], except_path: Path) -> set[str]:
    taken: set[str] = set()
    for dest, owner in owners.items():
        if owner == except_path:
            continue
        if dest.parent == dest_dir:
            taken.add(dest.stem)
            taken.add(dest.name)
    return taken


def _disambiguate(item: PlanItem, taken: set[str]) -> str:
    style_sep = "-" if "-" in item.proposed_name else "_"
    stem = Path(item.proposed_name).stem
    suffix = Path(item.proposed_name).suffix
    for token in item.extra_tokens:
        candidate = f"{stem}{style_sep}{token}"
        if candidate not in taken and f"{candidate}{suffix}" not in taken:
            return f"{candidate}{suffix}" if item.kind == "file" else candidate
    number = 2
    while True:
        candidate = f"{stem}{style_sep}{number}"
        label = f"{candidate}{suffix}" if item.kind == "file" else candidate
        if candidate not in taken and label not in taken:
            return label
        number += 1


def _resolve_collisions(
    items: list[PlanItem],
    all_paths: list[Path],
) -> list[PlanItem]:
    file_items = {Path(item.path): item for item in items if item.kind == "file"}
    dir_items = {Path(item.path): item for item in items if item.kind == "directory"}

    def names() -> tuple[dict[Path, str], dict[Path, str]]:
        return (
            {path: item.proposed_name for path, item in dir_items.items()},
            {path: item.proposed_name for path, item in file_items.items()},
        )

    paths = list(all_paths)
    for _ in range(len(paths) + len(items) + 5):
        dir_names, file_names = names()
        owners: dict[Path, Path] = {}
        conflict: tuple[Path, Path] | None = None
        for path in paths:
            dest = _relocate(path, dir_names, file_names)
            if dest in owners:
                conflict = (owners[dest], path)
                break
            owners[dest] = path
        if conflict is None:
            # Also reject a directory landing on an existing directory path that is not moving.
            dir_conflict = False
            for directory, item in dir_items.items():
                dest = _relocate(directory, dir_names, file_names)
                if dest in owners and owners[dest] != directory:
                    # A file owns this path. Disambiguate the directory.
                    taken = _taken_stems(dest.parent, {owners[dest]: owners[dest]}, directory)
                    # Stems of sibling destinations.
                    sibling_names = {
                        other.name
                        for other in owners
                        if other.parent == dest.parent and owners[other] != directory
                    }
                    item.proposed_name = _disambiguate(item, sibling_names | taken)
                    item.reason += " Renamed to avoid a collision."
                    item.confidence = round(max(0.5, item.confidence - 0.05), 2)
                    dir_conflict = True
                    break
            if not dir_conflict:
                return list(file_items.values()) + list(dir_items.values())
            continue
        left, right = conflict
        loser = _pick_loser(left, right, file_items)
        item = file_items.get(loser)
        if item is None:
            other = right if loser == left else left
            item = file_items.get(other)
            loser = other
        if item is None:
            # Neither path is a proposed file rename. Drop the lower-confidence directory.
            dir_item = _directory_to_yield(left, right, dir_items)
            if dir_item is None:
                break
            del dir_items[Path(dir_item.path)]
            continue
        dest = _relocate(loser, *names())
        taken = _taken_stems(dest.parent, owners, loser)
        updated = _disambiguate(item, taken)
        if updated == item.proposed_name:
            updated = _disambiguate(item, taken | {Path(item.proposed_name).stem})
        item.proposed_name = updated
        if "avoid a collision" not in item.reason:
            item.reason += " Renamed to avoid a collision."
        item.confidence = round(max(0.5, item.confidence - 0.05), 2)
    return list(file_items.values()) + list(dir_items.values())


def _pick_loser(left: Path, right: Path, file_items: dict[Path, PlanItem]) -> Path:
    left_item = file_items.get(left)
    right_item = file_items.get(right)
    if left_item is None and right_item is not None:
        return right
    if right_item is None and left_item is not None:
        return left
    if left_item is None or right_item is None:
        return right
    if left_item.confidence < right_item.confidence:
        return left
    if right_item.confidence < left_item.confidence:
        return right
    return right if right.as_posix() > left.as_posix() else left


def _directory_to_yield(
    left: Path,
    right: Path,
    dir_items: dict[Path, PlanItem],
) -> PlanItem | None:
    candidates = []
    for path in (left, right):
        for directory, item in dir_items.items():
            if path == directory or directory in path.parents:
                candidates.append(item)
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item.confidence, item.path))
    return candidates[0]


def _fill_paths(items: list[PlanItem], all_paths: list[Path]) -> list[dict[str, str]]:
    dir_names = {Path(item.path): item.proposed_name for item in items if item.kind == "directory"}
    file_names = {Path(item.path): item.proposed_name for item in items if item.kind == "file"}
    for item in items:
        if item.kind == "file":
            item.proposed_path = _relocate(Path(item.path), dir_names, file_names).as_posix()
        else:
            item.proposed_path = _relocate(Path(item.path), dir_names, file_names).as_posix()
    changes: list[dict[str, str]] = []
    for path in all_paths:
        dest = _relocate(path, dir_names, file_names)
        if dest != path:
            changes.append({"from": path.as_posix(), "to": dest.as_posix()})
    for item in items:
        if item.kind != "directory":
            continue
        dest = Path(item.proposed_path)
        if dest.as_posix() != item.path:
            changes.append({"from": item.path, "to": dest.as_posix()})
    return changes


def propose_heuristic(index: RepoIndex, config: Config) -> RenamePlan:
    """Propose renames without calling a model."""
    protection = Protection(index.root, config.protected)
    idf = _idf(index.files)
    items: list[PlanItem] = []
    skipped: list[dict[str, str]] = []
    file_map: dict[Path, PlanItem] = {}
    for signals in index.files:
        item, skip = _propose_file(signals, idf, config, protection)
        if item is not None:
            items.append(item)
            file_map[signals.path] = item
        elif skip is not None:
            skipped.append(skip)
    items.extend(_propose_directories(index, file_map, idf, config, protection))
    all_paths = [signals.path for signals in index.files]
    items = _resolve_collisions(items, all_paths)
    items.sort(key=lambda item: (item.kind != "directory", item.path))
    path_map = _fill_paths(items, all_paths)
    return RenamePlan(
        version=PLAN_VERSION,
        backend="none",
        root=str(index.root),
        items=items,
        path_map=path_map,
        warnings=[],
        skipped=skipped,
    )

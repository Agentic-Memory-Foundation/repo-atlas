"""Command line interface for repo-atlas."""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from repo_atlas import __version__
from repo_atlas.config import load_config
from repo_atlas.errors import RepoAtlasError
from repo_atlas.mapgen import parse_tool_list, render_map_body, write_maps
from repo_atlas.plan import load_plan, save_plan
from repo_atlas.propose.agent import build_agent_pack, ingest_agent_plan
from repo_atlas.propose.heuristic import propose_heuristic
from repo_atlas.propose.llm import propose_llm
from repo_atlas.scan import scan_repo
from repo_atlas.undo import latest_manifest, load_manifest, undo_manifest

OUT = Console()
ERR = Console(stderr=True)


def _path_arg(value: str) -> Path:
    return Path(value)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repo-atlas",
        description=(
            "Turn a repository tree into a name-based index for coding agents. "
            "Propose meaningful file and directory names, apply them safely, "
            "and write a feature map."
        ),
    )
    parser.add_argument("--version", action="version", version=f"repo-atlas {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Walk a repo and print per-file signals.")
    scan.add_argument("path", nargs="?", default=".", type=_path_arg)
    scan.add_argument("--json", action="store_true", help="Print signals as JSON.")

    propose = sub.add_parser("propose", help="Write a rename plan. This never changes files.")
    propose.add_argument("path", nargs="?", default=".", type=_path_arg)
    propose.add_argument(
        "--backend",
        choices=["none", "local", "agent", "api"],
        help="Override the configured backend. Default: none.",
    )
    propose.add_argument("--output", "-o", type=_path_arg, help="Write the plan JSON here.")
    propose.add_argument("--json", action="store_true", help="Print the plan as JSON.")
    propose.add_argument("--model", help="Model name for the local or api backend.")
    propose.add_argument("--base-url", help="OpenAI-compatible base URL for local or api.")
    propose.add_argument(
        "--min-confidence",
        type=float,
        help="Drop proposals below this confidence (0 to 1).",
    )

    apply = sub.add_parser(
        "apply",
        help="Show a rename diff. Pass --write to perform git mv and update imports.",
    )
    apply.add_argument("plan", type=_path_arg)
    apply.add_argument(
        "--write",
        action="store_true",
        help="Perform the renames. Default is a dry run.",
    )
    apply.add_argument(
        "--force",
        action="store_true",
        help="Rename even if tracked files are dirty.",
    )
    apply.add_argument(
        "--no-git",
        action="store_true",
        help="Rename with ordinary file moves instead of git mv.",
    )
    apply.add_argument(
        "--root",
        type=_path_arg,
        help="Repository root. Defaults to the path stored in the plan.",
    )
    apply.add_argument("--json", action="store_true")

    undo = sub.add_parser("undo", help="Reverse the latest apply. Pass --write to perform it.")
    undo.add_argument("manifest", nargs="?", type=_path_arg)
    undo.add_argument("--write", action="store_true", help="Perform the undo. Default is dry-run.")
    undo.add_argument("--root", type=_path_arg, default=None)
    undo.add_argument("--no-git", action="store_true")

    mapping = sub.add_parser("map", help="Write the feature map into agent instruction files.")
    mapping.add_argument("path", nargs="?", default=".", type=_path_arg)
    mapping.add_argument(
        "--tools",
        default="auto",
        help="Comma-separated list: agents,claude,cursor,copilot,gemini. Also auto or all.",
    )
    mapping.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the map instead of writing it.",
    )
    mapping.add_argument("--stdout", action="store_true", help="Also print the managed section.")

    ingest = sub.add_parser("ingest", help="Validate a plan filled in by an external agent.")
    ingest.add_argument("plan", type=_path_arg)
    ingest.add_argument("--output", "-o", required=True, type=_path_arg)
    ingest.add_argument("--root", type=_path_arg, default=None)
    return parser


def _print_plan(plan) -> None:
    if not plan.items:
        OUT.print("No renames proposed.")
    else:
        table = Table(title=f"Rename plan ({plan.backend})", show_lines=False)
        table.add_column("Kind")
        table.add_column("From")
        table.add_column("To")
        table.add_column("Conf", justify="right")
        table.add_column("Reason")
        for item in plan.items:
            table.add_row(
                item.kind,
                item.path,
                item.proposed_path or item.proposed_name,
                f"{item.confidence:.2f}",
                escape(item.reason),
            )
        OUT.print(table)
    if plan.skipped:
        OUT.print(f"Skipped {len(plan.skipped)} candidate(s).")
    for warning in plan.warnings:
        ERR.print(f"warning: {warning}")


def _diff_text(change) -> str:
    diff = difflib.unified_diff(
        change.before.splitlines(),
        change.after.splitlines(),
        fromfile=change.old_path,
        tofile=change.new_path,
        lineterm="",
    )
    return "\n".join(diff)


def _print_apply(report) -> None:
    if report.dry_run:
        OUT.print("Dry run. Pass --write to rename files.")
    if not report.moves and not report.changes:
        OUT.print("Nothing to rename.")
        return
    for src, dest in report.moves:
        OUT.print(f"rename {src} -> {dest}")
    for change in report.changes:
        OUT.print(_diff_text(change))
    if report.manifest_path:
        OUT.print(f"Undo manifest: {report.manifest_path}")


def _command_scan(args: argparse.Namespace) -> int:
    root = args.path.resolve()
    config = load_config(root)
    index = scan_repo(root, config)
    if args.json:
        payload = {
            "root": str(index.root),
            "files": [
                {
                    "path": item.path.as_posix(),
                    "language": item.language,
                    **item.to_summary(),
                }
                for item in index.files
            ],
            "skipped": [{"path": item.path, "reason": item.reason} for item in index.skipped],
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0
    OUT.print(f"Scanned {len(index.files)} file(s), skipped {len(index.skipped)}.")
    for item in index.files:
        symbol_names = ", ".join(symbol.name for symbol in item.symbols[:6]) or "-"
        OUT.print(f"{item.path.as_posix()}  {item.language}  {symbol_names}")
    return 0


def _apply_backend_overrides(config, args: argparse.Namespace) -> str:
    backend = args.backend or config.backend
    if args.min_confidence is not None:
        config.min_confidence = args.min_confidence
        config.validate()
    if backend == "local":
        if args.model:
            config.local_model = args.model
        if args.base_url:
            config.local_base_url = args.base_url
    elif backend == "api":
        if args.model:
            config.api_model = args.model
        if args.base_url:
            config.api_base_url = args.base_url
    return backend


def _command_propose(args: argparse.Namespace) -> int:
    root = args.path.resolve()
    config = load_config(root)
    backend = _apply_backend_overrides(config, args)
    index = scan_repo(root, config)
    if backend == "agent":
        plan, prompt = build_agent_pack(index, config)
        output = args.output or (root / "repo-atlas-agent-pack")
        if output.suffix == ".json":
            output.parent.mkdir(parents=True, exist_ok=True)
            save_plan(plan, output)
            prompt_path = output.with_name("PROMPT.md")
            prompt_path.write_text(prompt, encoding="utf-8")
            OUT.print(f"Wrote {output} and {prompt_path}")
        else:
            output.mkdir(parents=True, exist_ok=True)
            save_plan(plan, output / "plan.json")
            (output / "PROMPT.md").write_text(prompt, encoding="utf-8")
            OUT.print(f"Wrote an agent pack to {output}")
        OUT.print("Fill in proposed_name, reason, and confidence, then run repo-atlas ingest.")
        return 0
    if backend == "none":
        plan = propose_heuristic(index, config)
    elif backend in {"local", "api"}:
        plan = propose_llm(index, config, backend=backend)
    else:
        raise RepoAtlasError(f"Unknown backend {backend!r}.")
    if args.output:
        save_plan(plan, args.output)
        ERR.print(f"Wrote {args.output}")
    if args.json:
        sys.stdout.write(plan_to_json_text(plan))
        return 0
    _print_plan(plan)
    return 0


def plan_to_json_text(plan) -> str:
    from repo_atlas.plan import plan_to_json

    return plan_to_json(plan)


def _plan_root(plan, override: Path | None) -> Path:
    if override is not None:
        return override.resolve()
    recorded = Path(plan.root)
    if recorded.exists():
        return recorded.resolve()
    return Path.cwd().resolve()


def _command_apply(args: argparse.Namespace) -> int:
    from repo_atlas.apply import apply_plan

    plan = load_plan(args.plan)
    root = _plan_root(plan, args.root)
    config = load_config(root)
    index = scan_repo(root, config)
    files = [item.path for item in index.files]
    report = apply_plan(
        root,
        plan,
        files=files,
        write=args.write,
        force=args.force,
        use_git=not args.no_git,
    )
    if args.json:
        payload = {
            "dry_run": report.dry_run,
            "moves": [{"from": src, "to": dest} for src, dest in report.moves],
            "rewritten": [change.new_path for change in report.changes],
            "diffs": [_diff_text(change) for change in report.changes],
            "warnings": report.warnings,
            "manifest": report.manifest_path,
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0
    _print_apply(report)
    return 0


def _command_undo(args: argparse.Namespace) -> int:
    root = (args.root or Path.cwd()).resolve()
    if args.manifest:
        manifest = load_manifest(args.manifest)
        if args.root is None and manifest.root:
            recorded = Path(manifest.root)
            if recorded.exists():
                root = recorded.resolve()
    else:
        manifest = latest_manifest(root)
    report = undo_manifest(root, manifest, write=args.write, use_git=not args.no_git)
    if report.dry_run:
        OUT.print("Dry run. Pass --write to undo.")
    for src, dest in report.moves:
        OUT.print(f"rename {src} -> {dest}")
    for path in report.restored:
        OUT.print(f"restore {path}")
    if not report.moves and not report.restored:
        OUT.print("Nothing to undo.")
    return 0


def _command_map(args: argparse.Namespace) -> int:
    root = args.path.resolve()
    config = load_config(root)
    try:
        tools = parse_tool_list(args.tools, root)
    except ValueError as exc:
        raise RepoAtlasError(str(exc)) from exc
    index = scan_repo(root, config)
    if args.stdout or args.dry_run:
        OUT.print(render_map_body(index))
    paths = write_maps(root, index, tools, dry_run=args.dry_run)
    if args.dry_run:
        OUT.print("Dry run. Would write:")
    for path in paths:
        OUT.print(str(path))
    return 0


def _command_ingest(args: argparse.Namespace) -> int:
    draft = load_plan(args.plan)
    root = _plan_root(draft, args.root)
    config = load_config(root)
    index = scan_repo(root, config)
    plan = ingest_agent_plan(draft, index, config)
    save_plan(plan, args.output)
    OUT.print(f"Wrote {args.output}")
    _print_plan(plan)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    commands = {
        "scan": _command_scan,
        "propose": _command_propose,
        "apply": _command_apply,
        "undo": _command_undo,
        "map": _command_map,
        "ingest": _command_ingest,
    }
    try:
        return commands[args.command](args)
    except RepoAtlasError as exc:
        ERR.print(f"error: {exc}")
        return 1


def app() -> None:
    sys.exit(main())

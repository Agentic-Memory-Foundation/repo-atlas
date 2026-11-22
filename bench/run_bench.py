"""Run the messy-shop benchmark and write bench/results/messy_shop.json.

Usage:
    python bench/run_bench.py
    python bench/run_bench.py --check
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BENCH_ROOT = Path(__file__).resolve().parent
REPO_ROOT = BENCH_ROOT.parent
FIXTURE = BENCH_ROOT / "fixtures" / "messy_shop"
TASKS_PATH = BENCH_ROOT / "tasks.json"
RESULTS_PATH = BENCH_ROOT / "results" / "messy_shop.json"

sys.path.insert(0, str(BENCH_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from metrics import (  # noqa: E402
    hit_at,
    idf_map,
    map_locates,
    parse_features,
    rank_paths,
    simulate_agent,
)
from repo_atlas.config import load_config  # noqa: E402
from repo_atlas.scan import scan_repo  # noqa: E402


def _env() -> dict[str, str]:
    env = os.environ.copy()
    src = str(REPO_ROOT / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    env["GIT_AUTHOR_NAME"] = "Repo Atlas"
    env["GIT_AUTHOR_EMAIL"] = "atlas@example.com"
    env["GIT_COMMITTER_NAME"] = "Repo Atlas"
    env["GIT_COMMITTER_EMAIL"] = "atlas@example.com"
    return env


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, env=_env())


def _init_git(root: Path) -> None:
    env = _env()
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True, env=env)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=root,
        check=True,
        capture_output=True,
        env=env,
    )


def _paths_and_text(root: Path) -> tuple[list[str], dict[str, str]]:
    config = load_config(root)
    index = scan_repo(root, config)
    paths = [item.path.as_posix() for item in index.files]
    texts = {item.path.as_posix(): item.text for item in index.files}
    return paths, texts


def _evaluate(
    tasks: list[dict[str, str]], paths: list[str], texts: dict[str, str]
) -> dict[str, object]:
    weights = idf_map(paths)
    per_task = []
    hit1 = 0
    hit5 = 0
    calls = 0
    located = 0
    for task in tasks:
        ranked = rank_paths(task["question"], paths, weights)
        target = task["target"]
        at1 = hit_at(ranked, target, 1)
        at5 = hit_at(ranked, target, 5)
        agent = simulate_agent(task["question"], paths, target, texts.get(target, ""))
        hit1 += int(at1)
        hit5 += int(at5)
        calls += int(agent["calls"])
        located += int(bool(agent["hit"]))
        per_task.append(
            {
                "id": task["id"],
                "question": task["question"],
                "target": target,
                "hit_at_1": at1,
                "hit_at_5": at5,
                "rank": ranked.index(target) + 1 if target in ranked else None,
                "top": ranked[:5],
                "tool_calls": agent["calls"],
                "found_by": agent["found_by"],
                "needle": agent["needle"],
            }
        )
    return {
        "hit_at_1": hit1,
        "hit_at_5": hit5,
        "tool_calls": calls,
        "located": located,
        "tasks": per_task,
    }


def _relocate(path: str, path_map: list[dict[str, str]]) -> str:
    lookup = {entry["from"]: entry["to"] for entry in path_map}
    return lookup.get(path, path)


def run_fixture() -> dict[str, object]:
    tasks = json.loads(TASKS_PATH.read_text(encoding="utf-8"))["tasks"]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "messy_shop"
        shutil.copytree(FIXTURE, root)
        _init_git(root)
        before_paths, before_texts = _paths_and_text(root)
        before = _evaluate(tasks, before_paths, before_texts)
        plan_path = root / "plan.json"
        _run(
            [
                sys.executable,
                "-m",
                "repo_atlas",
                "propose",
                "--backend",
                "none",
                "-o",
                str(plan_path),
            ],
            root,
        )
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        _run([sys.executable, "-m", "repo_atlas", "apply", str(plan_path), "--write"], root)
        _run(
            [
                sys.executable,
                "-m",
                "repo_atlas",
                "map",
                "--tools",
                "agents,claude,cursor,copilot,gemini",
            ],
            root,
        )
        moved_tasks = []
        for task in tasks:
            updated = dict(task)
            updated["target"] = _relocate(task["target"], plan["path_map"])
            moved_tasks.append(updated)
        after_paths, after_texts = _paths_and_text(root)
        after = _evaluate(moved_tasks, after_paths, after_texts)
        agents = (root / "AGENTS.md").read_text(encoding="utf-8")
        features = parse_features(agents)
        map_hits = 0
        map_tasks = []
        for task in moved_tasks:
            found = map_locates(task["question"], features, task["target"])
            map_hits += int(found)
            map_tasks.append({"id": task["id"], "target": task["target"], "map_hit": found})
        renames = [
            {"from": item["path"], "to": item["proposed_path"], "reason": item["reason"]}
            for item in plan["items"]
        ]
        tree = sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and ".git" not in path.parts and path.name != "plan.json"
        )
    task_count = len(tasks)
    return {
        "fixture": "messy_shop",
        "backend": "none",
        "task_count": task_count,
        "before": {key: before[key] for key in ("hit_at_1", "hit_at_5", "tool_calls", "located")},
        "after": {key: after[key] for key in ("hit_at_1", "hit_at_5", "tool_calls", "located")},
        "map_hits": map_hits,
        "renames": renames,
        "before_tasks": before["tasks"],
        "after_tasks": after["tasks"],
        "map_tasks": map_tasks,
        "after_files": tree,
        "notes": {
            "hit_at_1": "Count of tasks whose target is the unique top name-only match.",
            "hit_at_5": "Count of tasks whose target is in the top 5 name-only matches.",
            "tool_calls": "Sum of glob and grep calls the simulated agent needs.",
            "located": "Tasks the simulated agent eventually finds, including the content grep.",
            "map_hits": "Tasks whose best AGENTS.md feature row lists the target file.",
        },
    }


def _headline(result: dict[str, object]) -> dict[str, object]:
    return {
        "task_count": result["task_count"],
        "before": result["before"],
        "after": result["after"],
        "map_hits": result["map_hits"],
    }


def _print(result: dict[str, object]) -> None:
    count = int(result["task_count"])
    before = result["before"]
    after = result["after"]
    assert isinstance(before, dict)
    assert isinstance(after, dict)
    print(f"tasks: {count}")
    print(
        "before  hit@1 {hit_at_1}/{n}  hit@5 {hit_at_5}/{n}  "
        "tool calls {tool_calls} (mean {mean:.2f})  located {located}/{n}".format(
            n=count,
            mean=before["tool_calls"] / count,
            **before,
        )
    )
    print(
        "after   hit@1 {hit_at_1}/{n}  hit@5 {hit_at_5}/{n}  "
        "tool calls {tool_calls} (mean {mean:.2f})  located {located}/{n}".format(
            n=count,
            mean=after["tool_calls"] / count,
            **after,
        )
    )
    print(f"map     {result['map_hits']}/{count}")
    print("renames:")
    renames = result["renames"]
    assert isinstance(renames, list)
    for item in renames:
        print(f"  {item['from']} -> {item['to']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the repo-atlas name-search benchmark.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if headline numbers differ from bench/results/messy_shop.json.",
    )
    parser.add_argument("--output", type=Path, default=RESULTS_PATH)
    args = parser.parse_args(argv)
    result = run_fixture()
    _print(result)
    if args.check:
        if not args.output.is_file():
            print(f"missing results file: {args.output}", file=sys.stderr)
            return 1
        committed = json.loads(args.output.read_text(encoding="utf-8"))
        if _headline(committed) != _headline(result):
            print("benchmark headline changed:", file=sys.stderr)
            print(json.dumps(_headline(result), indent=2), file=sys.stderr)
            return 1
        print("benchmark headline matches the committed results")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Contributing

Thanks for helping improve repo-atlas. The tool is a small library plus a command line interface, and the benchmark in `bench/` is part of the product: it is how we check that better names actually help name-only search.

## Setup

Python 3.10 or newer is required.

```bash
python -m pip install -e ".[dev]"
```

## Checks

```bash
ruff check src tests bench
ruff format src tests bench
pytest
python bench/run_bench.py
python -m build
```

`pytest` fails if coverage of `repo_atlas` drops below 85 percent. The benchmark writes `bench/results/messy_shop.json`. `python bench/run_bench.py --check` fails if those headline numbers drift, so update the committed JSON, `BENCHMARK.md`, and the README table in the same change.

## Pull requests

- Keep the public commands stable: `scan`, `propose`, `apply`, `undo`, `map`, and `ingest`.
- New language support belongs in a rewriter registered with `repo_atlas.rewrite.register_rewriter`.
- Do not rename protected paths in order to make a fixture look better. Adjust the heuristic, and let the benchmark report the real result.
- Tests should create their own temporary git repositories. Do not point tests at the checkout you are editing.
- Write commit messages that say what changed and why.

## Style

- Type hints on public functions.
- No em dashes in documentation, comments, or user-facing strings.
- Format with Ruff. The line length is 100.

## Reporting bugs

Please include the command you ran, the backend (`none`, `local`, `api`, or `agent`), and whether the tree was a git checkout. A minimal repository that reproduces the rename or import mistake is ideal.

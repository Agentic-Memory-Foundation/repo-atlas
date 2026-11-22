# repo-atlas

Coding agents spend a lot of effort grepping and globbing file names. When a file is called `utils.py` or a directory is called `misc/`, the name says nothing about the code inside, so the agent has to open files until it guesses right. repo-atlas treats the directory tree as a search index: it proposes names that describe the code (`verify_stripe_webhook_signature.py`, `billing/`), renames them safely, and writes a feature map the agent can read first.

The idea comes from Parag Paul: meaningful slugs make name-based search work, so agents stop guessing where to look.

## Install

Python 3.10 or newer.

```bash
pip install repo-atlas
```

From a checkout of this repository:

```bash
pip install -e ".[dev]"
```

The command is `repo-atlas`. `python -m repo_atlas` is the same entry point.

## Quickstart

```bash
repo-atlas scan .
repo-atlas propose --backend none -o plan.json
repo-atlas apply plan.json
repo-atlas apply plan.json --write
repo-atlas map
```

`propose` never changes files. `apply` is a dry run until you pass `--write`. `map` writes `AGENTS.md` (and other agent guides when you ask).

## Scan

`repo-atlas scan` walks the repository from the git root. It honors `.gitignore` and nested ignore files, and it skips:

- binaries, files with null bytes, and files larger than 1 MB
- vendored and generated directories (`node_modules`, `vendor`, `dist`, `.venv`, `__pycache__`, and similar)
- lockfiles and minified bundles
- hidden paths and symlinks

For each remaining file it records the language, public symbols, docstrings, comments, imports, and the current file name. `scan --json` prints that index.

## Propose

`repo-atlas propose` writes a rename plan. Each item has a path, a proposed name, a reason, and a confidence from 0 to 1. Proposals below `min_confidence` (default 0.5) are dropped. Four backends are available.

### `none` (default)

No model. The name comes from the code:

- One public function or class becomes the file name (Python `snake_case`, JavaScript and TypeScript `kebab-case`).
- Several symbols are scored against the docstring and TF-IDF keywords from the file.
- A generic directory (`misc`, `lib`, `utils`, `helpers`, `stuff`, and the same stems with a trailing number) is renamed when the files inside share a token. `misc/` full of billing helpers becomes `billing/`.
- Structural directories (`src`, `tests`, `app`, `pages`, `migrations`, and similar) stay put.

### `local`

Sends the same signals to a small model on an OpenAI-compatible server (Ollama, llama.cpp, LM Studio). The default base URL is `http://127.0.0.1:11434/v1` and the default model is `qwen2.5-coder:7b`.

```bash
repo-atlas propose --backend local --base-url http://127.0.0.1:11434/v1 --model qwen2.5-coder:7b
```

A suggestion that is not a valid name for that language is discarded, and the heuristic name is kept for that file.

### `api`

Same request shape, against a hosted OpenAI-compatible API. The default endpoint is `https://api.openai.com/v1` and the default model is `gpt-4o-mini`. The key is read from `REPO_ATLAS_API_KEY` (or the env var named by `api_key_env` in config).

### `agent`

No model inside the tool. `propose --backend agent` writes `repo-atlas-agent-pack/plan.json` and `PROMPT.md`. Fill `proposed_name`, `reason`, and `confidence` with the coding agent you already use (Claude Code, Codex, Cursor, Pi, or anything else), then ingest the file:

```bash
repo-atlas ingest repo-atlas-agent-pack/plan.json --output plan.json
repo-atlas apply plan.json
repo-atlas apply plan.json --write
```

An empty `proposed_name` keeps the current name. A confidence of 0 is treated as 0.75. Names that point outside the repo, change the extension, or collide are rejected.

## Apply, undo, and imports

```bash
repo-atlas apply plan.json            # dry run: renames plus a diff of rewritten files
repo-atlas apply plan.json --write    # git mv, then rewrite imports
repo-atlas undo                       # preview the last undo
repo-atlas undo --write               # restore paths and file contents
```

Safety rules:

- A git tree with tracked modifications is refused unless you pass `--force`. Untracked files do not count as dirty.
- Tracked paths move with `git mv`. `--no-git` uses ordinary moves, including in a directory that is not a git repository.
- An undo manifest is written under `.git/repo-atlas/undo/<timestamp>/manifest.json`. Undo restores file contents, then reverses the moves.
- Python modules are `snake_case` identifiers. A configured `kebab` style does not apply to Python.
- Two files that want the same name are disambiguated with an extra token, then a numeric suffix.
- These paths are never renamed: `README`, `LICENSE`, package manifests, `Dockerfile`, hidden files, `__init__.py`, `__main__.py`, `manage.py`, `conftest.py`, language entry files (`main.go`, `lib.rs`, `index.js`, and similar), entry points declared in `package.json` or `pyproject.toml`, test discovery patterns (`test_*.py`, `*_test.py`, `*.test.js`, `*.spec.ts`, and similar), Django migrations, `alembic/versions`, and Next.js app or pages conventions (`page`, `layout`, `route`, and related file names). Add more with the `protected` glob list.

Import rewriting covers Python `import` and `from` (relative and absolute, including `from package import submodule`), JavaScript and TypeScript relative `import` / `require` / `import()`, and Markdown links and inline code that mention a moved path. Other languages can register a rewriter:

```python
from repo_atlas.rewrite import register_rewriter
```

The rewriter implements `handles(path) -> bool` and `rewrite(source, path, context) -> str`.

## Feature map

`repo-atlas map` writes a feature list (one line per file: path and a short title taken from the docstring or the primary symbol) and a directory guide. Both live between these markers:

```html
<!-- repo-atlas:start -->
<!-- repo-atlas:end -->
```

Text outside the markers is preserved. Running `map` again replaces only the managed section.

`--tools auto` (the default) writes `AGENTS.md` and any other guide the repository already uses. `--tools all` also writes:

| Tool | File |
| --- | --- |
| agents | `AGENTS.md` |
| claude | `CLAUDE.md` |
| cursor | `.cursor/rules/repo-atlas.mdc` |
| copilot | `.github/copilot-instructions.md` |
| gemini | `GEMINI.md` |

Pass a comma-separated list (`--tools agents,cursor`) to choose a subset. `--dry-run` prints the section and writes nothing.

## Configuration

Settings load in this order: built-in defaults, `[tool.repo-atlas]` in `pyproject.toml`, `repo-atlas.toml`, environment variables, then CLI flags.

```toml
backend = "none"
naming_style = "auto" # auto, snake, kebab, camel
min_confidence = 0.5
include = []
exclude = ["scratch/**"]
protected = ["legacy/keep_this_name.py"]
timeout_seconds = 60
batch_size = 8

[local]
base_url = "http://127.0.0.1:11434/v1"
model = "qwen2.5-coder:7b"

[api]
base_url = "https://api.openai.com/v1"
model = "gpt-4o-mini"
api_key_env = "REPO_ATLAS_API_KEY"
```

Environment variables: `REPO_ATLAS_LOCAL_BASE_URL`, `REPO_ATLAS_LOCAL_MODEL`, `REPO_ATLAS_API_BASE_URL`, `REPO_ATLAS_API_MODEL`. The API key uses `api_key_env` (default `REPO_ATLAS_API_KEY`). `REPO_ATLAS_LOCAL_API_KEY` is sent when the local server asks for a bearer token.

`include` limits the scan to those globs. `exclude` and `protected` are extra globs on top of the built-in skips and protected names.

## Example

`bench/fixtures/messy_shop` is a small shop app whose names do not describe the code. The `none` backend, applied in the benchmark run recorded in `bench/results/messy_shop.json`, renames:

| Before | After |
| --- | --- |
| `shop/utils.py` | `shop/verify_stripe_webhook_signature.py` |
| `shop/helpers.py` | `shop/calculate_invoice_tax.py` |
| `shop/misc/` | `shop/billing/` |
| `shop/misc/stuff2.py` | `shop/billing/send_password_reset_email.py` |
| `shop/misc/tmp.py` | `shop/billing/apply_discount_code.py` |
| `shop/lib/` | `shop/invoice/` |
| `shop/lib/data.py` | `shop/invoice/parse_invoice_csv.py` |
| `shop/lib/file.py` | `shop/invoice/sum_invoice_totals.py` |
| `web/helpers.js` | `web/calculate-cart-total.js` |
| `web/misc/` | `web/checkout/` |
| `web/misc/file2.ts` | `web/checkout/format-currency.ts` |
| `web/misc/stuff.ts` | `web/checkout/validate-coupon-code.ts` |

Left in place: `shop/create_stripe_refund.py` (already specific), `shop/storage.py`, `manage.py`, `shop/migrations/0001_initial.py`, `tests/test_utils.py`, `web/index.js`, and `README.md`. Imports in `shop/__init__.py`, `manage.py`, `web/index.js`, and the link in `docs/overview.md` are rewritten to the new paths. `vendor/` and `ignored_vendor/` are not scanned.

Before:

```text
shop/
  utils.py
  helpers.py
  create_stripe_refund.py
  storage.py
  misc/
    stuff2.py
    tmp.py
  lib/
    data.py
    file.py
web/
  helpers.js
  index.js
  misc/
    file2.ts
    stuff.ts
```

After `propose --backend none` and `apply --write`:

```text
shop/
  verify_stripe_webhook_signature.py
  calculate_invoice_tax.py
  create_stripe_refund.py
  storage.py
  billing/
    send_password_reset_email.py
    apply_discount_code.py
  invoice/
    parse_invoice_csv.py
    sum_invoice_totals.py
web/
  calculate-cart-total.js
  index.js
  checkout/
    format-currency.ts
    validate-coupon-code.ts
```

## Benchmark

`python bench/run_bench.py` copies the fixture into a temporary git repository, measures name-only search, runs the `none` backend, applies the plan, writes the feature map, and measures again. The committed result (`bench/results/messy_shop.json`, produced by that script on 2026-11-22) is:

| | hit@1 | hit@5 | tool calls | located | AGENTS.md map |
| --- | ---: | ---: | ---: | ---: | ---: |
| Before | 1/10 | 1/10 | 63 (mean 6.30) | 10/10 | |
| After | 10/10 | 10/10 | 10 (mean 1.00) | 10/10 | 10/10 |

The single hit before the rename is the question "where are stripe refunds created?", whose target is already `shop/create_stripe_refund.py`. After the rename, every task's target is the top name-only match, and the simulated agent finds it with one glob. Content search still locates every task before the rename, which is why `located` stays 10/10 while the tool-call count drops from 63 to 10. The map alone locates all 10 tasks. Definitions, the task list, and per-task rows are in [BENCHMARK.md](BENCHMARK.md).

## Development

```bash
ruff check src tests bench
ruff format --check src tests bench
pytest
python bench/run_bench.py --check
python -m build
```

`pytest` requires 85 percent coverage of `repo_atlas`. See [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).

## License

MIT. Copyright (c) 2026 Agentic Memory Foundation.

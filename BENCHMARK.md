# Benchmark

repo-atlas claims that descriptive file and directory names make name-only search land on the right file, and that a generated feature map does the same without opening the file. This document reports one measured run. The numbers are the output of `python bench/run_bench.py`. They are also stored in `bench/results/messy_shop.json`. Do not edit either by hand. If a change moves the headline counts, rerun the script and update this page and the README table together.

## How to reproduce

```bash
pip install -e ".[dev]"
python bench/run_bench.py
python bench/run_bench.py --check
```

The script copies `bench/fixtures/messy_shop` into a temporary directory, creates a git commit, measures the tasks, runs `repo-atlas propose --backend none`, applies the plan with `git mv`, writes the five agent guide files, and measures again. `--check` reruns that sequence and exits non-zero if `task_count`, `hit_at_1`, `hit_at_5`, `tool_calls`, `located`, or `map_hits` differ from the committed JSON. Continuous integration runs `--check` on Python 3.10 through 3.13.

The run recorded here was produced on 2026-11-22 with the `none` backend (no model).

## Fixture

`bench/fixtures/messy_shop` is a small shop application. Generic names (`utils.py`, `helpers.py`, `misc/`, `stuff2.py`, `tmp.py`, `lib/`, `data.py`, `file.py`, `helpers.js`, `file2.ts`, `stuff.ts`) sit next to a few names that already describe the code (`create_stripe_refund.py`). The scan skips `vendor/` (a vendored directory), `ignored_vendor/` (gitignored), and `assets/logo.png` (binary suffix). Protected paths that stay put include `manage.py`, `shop/migrations/0001_initial.py`, `tests/test_utils.py`, `web/index.js`, and `README.md`.

The applied renames are listed in the README example and in the `renames` array of the results JSON. Twelve paths change: three directories and nine files.

## Tasks

`bench/tasks.json` has ten questions. The target is the path before any rename. The runner follows `path_map` so the after measurement uses the new path.

| id | question | target before |
| --- | --- | --- |
| webhook | where is the code that verifies webhook signatures? | `shop/utils.py` |
| invoice-tax | where is the invoice tax calculated? | `shop/helpers.py` |
| password-reset | where are password reset emails sent? | `shop/misc/stuff2.py` |
| discount | where is a billing discount code applied? | `shop/misc/tmp.py` |
| invoice-csv | where are invoice CSV rows parsed? | `shop/lib/data.py` |
| invoice-totals | where are invoice totals summed? | `shop/lib/file.py` |
| cart-total | where is the shopping cart total calculated? | `web/helpers.js` |
| currency | where is currency formatted for display? | `web/misc/file2.ts` |
| coupon | where are coupon codes validated? | `web/misc/stuff.ts` |
| refund | where are stripe refunds created? | `shop/create_stripe_refund.py` |

## Metrics

Implemented in `bench/metrics.py`.

- Tokens are lowercase words split on punctuation, underscores, hyphens, and camel case.
- Question words are dropped (`where`, `is`, `the`, `code`, and the rest of the stop list in that file).
- A light stemmer matches `signatures` to `signature`, `verifies` to `verify`, `formatted` to `format`, and `applied` to `apply`.
- **hit@k** ranks files by the sum of IDF weights of task tokens that appear in the path. A score of 0 is a miss, so a small repository does not make every file a hit.
- **Tool calls** are what a small simulated agent spends. It issues one glob per stemmed keyword, longest first. A glob counts as a find when the target is in the result and the result has 1 to 5 files. If those miss, it tries pairwise globs of the three longest needles, then one content grep of the longest needle against file text.
- **Located** counts tasks that simulated agent eventually finds, including the content grep.
- **Map hit** reads `AGENTS.md`. A feature row matches when task keywords overlap the description (the path itself is not used as evidence). Directory-guide rows, which end in `/`, are skipped. Ties are allowed.

## Results

Headline counts from `bench/results/messy_shop.json`:

| | hit@1 | hit@5 | tool calls | located | map hits |
| --- | ---: | ---: | ---: | ---: | ---: |
| Before | 1/10 | 1/10 | 63 | 10/10 | |
| After | 10/10 | 10/10 | 10 | 10/10 | 10/10 |

Mean tool calls: 6.30 before, 1.00 after.

### Before, name-only search and simulated agent

| id | hit@1 | hit@5 | rank | tool calls | found by |
| --- | --- | --- | --- | ---: | --- |
| webhook | no | no | | 7 | grep |
| invoice-tax | no | no | | 4 | grep |
| password-reset | no | no | | 8 | grep |
| discount | no | no | | 7 | grep |
| invoice-csv | no | no | | 7 | grep |
| invoice-totals | no | no | | 7 | grep |
| cart-total | no | no | | 8 | grep |
| currency | no | no | | 7 | grep |
| coupon | no | no | | 7 | grep |
| refund | yes | yes | 1 | 1 | glob |

The only name-only hit is `refund`. Its path is already `shop/create_stripe_refund.py`, so the glob for `refund` returns that file alone. Every other task misses hit@5 (the ranked list is empty, or the target is outside the top 5) and the simulated agent falls through to a content grep. That is why every task is still located, at a cost of 63 tool calls.

### After `none` + apply + map

| id | target after | hit@1 | hit@5 | rank | tool calls | found by | map |
| --- | --- | --- | --- | ---: | ---: | --- | --- |
| webhook | `shop/verify_stripe_webhook_signature.py` | yes | yes | 1 | 1 | glob | yes |
| invoice-tax | `shop/calculate_invoice_tax.py` | yes | yes | 1 | 1 | glob | yes |
| password-reset | `shop/billing/send_password_reset_email.py` | yes | yes | 1 | 1 | glob | yes |
| discount | `shop/billing/apply_discount_code.py` | yes | yes | 1 | 1 | glob | yes |
| invoice-csv | `shop/invoice/parse_invoice_csv.py` | yes | yes | 1 | 1 | glob | yes |
| invoice-totals | `shop/invoice/sum_invoice_totals.py` | yes | yes | 1 | 1 | glob | yes |
| cart-total | `web/calculate-cart-total.js` | yes | yes | 1 | 1 | glob | yes |
| currency | `web/checkout/format-currency.ts` | yes | yes | 1 | 1 | glob | yes |
| coupon | `web/checkout/validate-coupon-code.ts` | yes | yes | 1 | 1 | glob | yes |
| refund | `shop/create_stripe_refund.py` | yes | yes | 1 | 1 | glob | yes |

Each task's target is rank 1. The simulated agent stops on the first glob, so the tool-call total is 10. The AGENTS.md feature row for each task names the target file.

## What this does not show

This is one fixture and the deterministic `none` backend. It does not measure a hosted model, and it does not measure a human agent's behavior on a large repository. The simulated agent is a fixed glob-then-grep policy defined in `bench/metrics.py`, so the tool-call counts are comparable across runs of this script and are not a trace from Claude, Codex, or Cursor. A content grep still finds the old generic files, which is the 10/10 located score before the rename.

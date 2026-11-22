# Benchmark

`python bench/run_bench.py` copies `fixtures/messy_shop` into a temporary git repository, measures name-only search, runs `repo-atlas propose --backend none`, applies the plan, writes `AGENTS.md`, and measures the same tasks again.

`python bench/run_bench.py --check` reruns the fixture and fails if the headline counts differ from `results/messy_shop.json`.

The metric definitions live in `metrics.py` and are repeated in `BENCHMARK.md`. Numbers in the docs come from that script. Do not edit them by hand.

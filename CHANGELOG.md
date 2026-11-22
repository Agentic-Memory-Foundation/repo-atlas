# Changelog

## 0.1.0 - 2026-11-22

First release of repo-atlas.

- Scan a repository, honor `.gitignore`, and skip binaries, vendored directories, generated files, and lockfiles.
- Extract symbols, docstrings, comments, and imports from Python, JavaScript, TypeScript, and a few other languages.
- Propose file and directory renames with four backends: `none` (deterministic heuristics, the default), `local` (OpenAI-compatible local server), `api` (hosted OpenAI-compatible key), and `agent` (a prompt pack for the coding agent you already pay for).
- Apply is a dry run until `--write`. Writes use `git mv` when the tree is clean, update Python and JavaScript or TypeScript imports, record an undo manifest, and can be reversed with `undo`.
- Refuse to rename protected names: readmes, licenses, manifests, entry points, test discovery patterns, hidden paths, Django migrations, and Next.js app-router conventions.
- Generate a feature map in `AGENTS.md` and, when asked, `CLAUDE.md`, `.cursor/rules/repo-atlas.mdc`, `.github/copilot-instructions.md`, and `GEMINI.md`. Managed sections keep the surrounding notes.
- Configure the run with `repo-atlas.toml` or `[tool.repo-atlas]` in `pyproject.toml`.
- Ship a reproducible benchmark on a messy fixture repository.

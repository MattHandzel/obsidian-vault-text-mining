# Repository Guidelines

## Project Structure & Module Organization
- Core package lives in `self_extract/` with pipeline stages split by concern: `scan.py` enumerates notes, `chunker.py` slices content, `pipeline.py` orchestrates runs, `aggregate.py` reconciles facts, and `cli.py` exposes commands via Typer.
- Configuration templates sit at repo root (`config.yaml`, `config.example.yaml`) and prompts at `prompts.yaml`; adjust them before running the pipeline.
- Generated artefacts write to `output/` (`profile.json`, `profile.runs.jsonl`). Keep this directory out of commits unless sharing sample data.

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt` — create a local environment if you skip `nix-shell`.
- `python -m self_extract.cli init-config` — scaffold a fresh `config.yaml` tuned to your vault path.
- `python -m self_extract.cli run -c config.yaml` — execute the extraction pipeline using the active configuration.
- `python -m self_extract.cli query --profile output/profile.json --bucket goals --search "exercise"` — inspect aggregated results; add `--raw` to review chunk-level evidence.

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation and module-level logging (`rich` console helpers) instead of ad-hoc prints.
- Use snake_case for functions and variables, CapWords for Typer command classes, and keep module names descriptive (`profile_query.py` vs generic helpers).
- Write docstrings for CLI entry points and public pipeline helpers; prefer explicit imports over `*`.

## Testing Guidelines
- Targeted unit or integration tests should live under a future `tests/` package using `pytest`; seed fixtures with small markdown notes stored under `tests/fixtures`.
- Run `pytest` locally before submitting; when touching the pipeline, include a smoke run (`python -m self_extract.cli run -c config.yaml --limit 1`) to validate configuration paths.

## Commit & Pull Request Guidelines
- Base commit messages on the existing history: short (≤72 chars), present-tense summaries like `Add chunk cache guard`. Include scope tags only if they clarify.
- Pull requests should document configuration changes, sample command outputs, and any new dependencies. Link issues, note manual steps (e.g., regenerate prompts), and attach excerpts from `output/profile.runs.jsonl` when troubleshooting aggregation.

## Configuration & Secrets
- Never commit real vault content or credentialed configs. Use `config.example.yaml` as the baseline, and document any new keys there alongside updates to `README.md`.

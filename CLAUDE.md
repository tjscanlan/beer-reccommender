# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Beer Recommendation App (see [README.md](README.md)): a FastAPI backend serving a JSON API plus a PWA frontend that installs to an iPhone home screen.

- [main.py](main.py) — entrypoint; runs uvicorn on `0.0.0.0:8000` so phones on the LAN can reach it.
- [backend/main.py](backend/main.py) — FastAPI app: `/api/health`, `/api/beers`, `/api/search`, `POST /api/recommend`; mounts [frontend/](frontend/) as static root (mounted last so `/api/*` wins).
- [backend/catalog.py](backend/catalog.py) + [backend/data/beers.json](backend/data/beers.json) — bundled 60-beer dataset; each beer has an 8-axis flavor profile (`FLAVOR_KEYS`).
- [backend/recommender.py](backend/recommender.py) — numpy content-based recommender: cosine similarity over flavor vectors + normalized ABV/IBU; keyword heuristics parse free-text taste preferences; results capped at two per style.
- [backend/ai.py](backend/ai.py) — optional Claude (`claude-opus-4-8`) call that personalizes recommendation reasons; gated on `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`, fails silently to template reasons.
- [backend/untappd.py](backend/untappd.py) — optional Untappd v4 search proxy, gated on `UNTAPPD_CLIENT_ID`/`UNTAPPD_CLIENT_SECRET` (Untappd is closed to new API registrations; local catalog is the fallback).
- [frontend/](frontend/) — vanilla-JS PWA (manifest, service worker, iOS meta tags, generated PNG icons). No build step.

When adding dependencies, use `uv add <package>` so `pyproject.toml`, the lockfile, and the venv stay in sync.

## Environment

- Python `>=3.9` (pinned to 3.9 in [.python-version](.python-version)).
- Managed with `uv` (`pyproject.toml` + `uv.lock`).
- An `.env` file exists at the repo root for local secrets/config (e.g. Untappd/Anthropic API credentials) — it's currently empty and is not committed practice to inspect/print its contents.

## Common commands

```bash
# install/sync dependencies into .venv
uv sync

# run the top-level entrypoint
uv run python main.py

# add a new dependency (updates pyproject.toml and uv.lock)
uv add <package>
```

There are no lint, test, or build tooling configured yet — no test framework, linter, or formatter is set up in this repo as of now.

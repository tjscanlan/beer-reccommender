# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Beer Recommendation App (see [README.md](README.md)): a FastAPI backend serving a JSON API plus a PWA frontend that installs to an iPhone home screen.

- [main.py](main.py) — local-dev entrypoint (uvicorn on `0.0.0.0:8000` so phones on the LAN can reach it); also re-exports `app` so Vercel's FastAPI preset finds it here.
- [backend/main.py](backend/main.py) — FastAPI app: `/api/health`, `/api/beers`, `/api/search`, `POST /api/recommend`; mounts [public/](public/) as static root (mounted last so `/api/*` wins).
- [backend/catalog.py](backend/catalog.py) + [backend/data/beers.json](backend/data/beers.json) — bundled 60-beer dataset; each beer has an 8-axis flavor profile (`FLAVOR_KEYS`).
- [backend/recommender.py](backend/recommender.py) — numpy content-based recommender: cosine similarity over flavor vectors + normalized ABV/IBU; keyword heuristics parse free-text taste preferences; results capped at two per style.
- [backend/ai.py](backend/ai.py) — optional Claude (`claude-opus-4-8`) call that personalizes recommendation reasons; gated on `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`, fails silently to template reasons.
- [backend/untappd.py](backend/untappd.py) — optional Untappd v4 search proxy, gated on `UNTAPPD_CLIENT_ID`/`UNTAPPD_CLIENT_SECRET` (Untappd is closed to new API registrations; local catalog is the fallback).
- [public/](public/) — vanilla-JS PWA (manifest, service worker, iOS meta tags, generated PNG icons). No build step; served from Vercel's CDN in production.

## Deployment (Vercel)

Deployed via Vercel's Git integration and native FastAPI preset: pushes to `main` go to production, PR branches get preview deploys. The root [main.py](main.py) re-exports `app` for Vercel's entrypoint detection; [public/](public/) is served from the CDN (the StaticFiles mount is the local-dev/fallback path); deps install from `pyproject.toml` + committed `uv.lock`. `ANTHROPIC_API_KEY` is a Sensitive Vercel env var scoped to Production only. Abuse protection for the paid `/api/recommend` call: Pydantic input caps + capped/timeboxed Claude call in code, plus a Vercel Firewall rate-limit rule and an Anthropic Console spend cap (dashboard-side).

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

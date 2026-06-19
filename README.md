# home-search

A private system for finding a second home: ingest listings (Zillow URL/area,
Redfin CSV, or manual), view promo material, tag/rate/track properties against
flexible criteria, upload your own media and notes, see homes on a map and as a
list, and compute drive-times to amenities.

Backend + web now; iOS later. ~2–3 users, ~50 properties. Full design in
[PLAN.md](PLAN.md); architecture/commands for contributors in [CLAUDE.md](CLAUDE.md).

## Stack

FastAPI + SQLAlchemy + Alembic + SQLite (Postgres-swappable) · React + Vite ·
APScheduler · Docker Compose · runs on boulder-server over Tailscale.

## Quick start (local dev)

**One command — run both servers:**

```bash
./dev.sh
```

This creates the backend venv, installs deps on first run (and re-installs when
`requirements.txt` / `package.json` change), applies DB migrations, and starts
the backend (http://localhost:8000, docs at `/docs`) and frontend
(http://localhost:3000, which proxies `/api` → backend). Ctrl+C stops both.

On first run, create the initial user (auth-gated routes need one — `dev.sh`
prints this reminder if no users exist):

```bash
cd backend && source .venv/bin/activate && python seed_user.py you@example.com "Your Name" <password>
```

Then sign in with that user.

<details><summary>Manual / two-terminal setup</summary>

```bash
# terminal 1 — backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload

# terminal 2 — frontend
cd frontend && npm install && npm run dev
```
</details>

## Tests

```bash
cd backend && source .venv/bin/activate && pytest      # 35 tests
```

## Production

`docker compose up -d --build` — see [ops/README.md](ops/README.md) for
deployment, nightly restic backups to both Synology NAS units, and the
SF-server warm standby.

## Configuration

All config is environment-driven (see [.env.example](.env.example)). External
API keys (Zillow via RapidAPI, Google Maps Platform) are optional — the app
runs without them (manual entry, no map/distances) and degrades gracefully when
they're absent. The browser never sees server-side keys; all third-party calls
are made by the backend and cached in the DB.

## Status

Phases 0–6 of the plan are implemented (backend, frontend, ingestion, criteria,
distances, ops). Phase 7 (iOS) is future work against the same OpenAPI surface.

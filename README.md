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

**Backend** (http://localhost:8000, docs at `/docs`):

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env          # set a JWT_SECRET_KEY at minimum
alembic upgrade head
python seed_user.py you@example.com "Your Name" <password>   # first user
uvicorn app.main:app --reload
```

**Frontend** (http://localhost:3000, proxies `/api` → backend):

```bash
cd frontend
npm install
npm run dev
```

Then sign in with the user you seeded.

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

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

Phases 0–6 of `PLAN.md` §12 are implemented and verified (backend + frontend +
ingestion + criteria + distances + ops). Phase 7 (iOS) is future work against the
same OpenAPI surface. **`PLAN.md` remains the authoritative spec** — read the
relevant section before extending a subsystem.

## What this is

A personal system for finding a second home: search an area against flexible criteria, view promo material, tag/rate/track properties, upload own media, view homes on a map and list, and compute drive-times to amenities. Backend + web now, iOS later. ~2–3 users, ~50 properties. Architecture deliberately **mirrors the `tracker` project** (FastAPI + React) — consult `/Users/steve/Projects/tracker` for established patterns.

## Stack & layout

- **Backend**: FastAPI + SQLAlchemy + Alembic + SQLite in `backend/app/` — `main.py` (router includes + lifespan), `config.py` (pydantic-settings), `database.py`, `models.py`, `schemas.py`, `auth.py`, `routers/` (auth, properties, tags, criteria, media, places, ingest), `services/` (storage, scoring, zillow, redfin_csv, maps, scheduler). Migrations in `backend/alembic/`.
- **Frontend**: React + Vite in `frontend/src/` — `api.js` (one axios client), `auth.jsx` (context), `pages/` (Login, ListView, MapView, Detail, CriteriaAdmin), `components/` (FilterBar, AddPropertyBar, CriteriaPanel, MediaGallery).
- **Monorepo dirs**: `backend/`, `frontend/`, `ops/`, `ios/` (later).

## Commands

All verified. Backend (run from `backend/`, venv in `backend/.venv`):

```bash
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head                       # apply migrations
alembic revision --autogenerate -m "..."   # new migration after model change
python seed_user.py <email> <name> <pw>    # bootstrap first user (auth-gated routes need one)
uvicorn app.main:app --reload              # dev server :8000, docs at /docs
pytest                                     # 35 tests; pytest tests/test_criteria.py for one file
```

Frontend (from `frontend/`): `npm install`, `npm run dev` (:3000, proxies `/api`→:8000), `npm run build`.
Full stack: `docker compose up -d --build` from repo root, then `docker compose exec backend python seed_user.py …`.

**Gotcha**: `passlib` 1.7.4 needs `bcrypt==4.0.1` pinned (bcrypt ≥4.1 drops `__about__` and auth hashing breaks). `EmailStr` requires `pydantic[email]`. Both are in `requirements.txt`.

## Architecture notes that span files

- **All third-party API calls are server-side** (Zillow via RapidAPI `zillow-com1`, Google Maps Platform). Keys live in `.env` and never reach the browser. Every raw response is cached in the DB (`Property.raw_payload`, `PlaceDistance.raw`); the app reads from the DB and only hits an API on explicit add or a scheduled refresh. Promo photos are **downloaded and stored locally** (persistence + privacy, no hotlinking).

- **Flexible typed criteria** are the core of the data model (PLAN.md §4). One `Criterion` definition table (`value_type` ∈ boolean|number|rating|enum|text, plus unit/scale/options/weight/`is_subjective`) and one unified `CriterionValue` table with typed columns (`value_number`, `value_bool`, `value_text`). `CriterionValue.user_id` is **non-null with sentinel `0`** (`OBJECTIVE_USER_ID` in `models.py`) for the shared objective value, or a real user id for a subjective rating — a plain `UniqueConstraint(property_id, criterion_id, user_id)` then works without COALESCE (the plan's NULL+COALESCE approach was simplified to a sentinel). Routing of which typed column to write lives in `routers/criteria.py:_assign_typed_value`; scoring (normalize → mean across users → weighted) in `services/scoring.py`. Objective values drive filters (`criterion[<id>]=<op>:<val>` parsed in `routers/properties.py`); subjective ratings drive the weighted household score.

- **Portability is a first-class constraint**, design accordingly: all config via env vars (no hardcoded paths/hosts/Tailscale IPs); a storage abstraction (`services/storage.py`) with `local` and `s3` drivers selectable by `STORAGE_BACKEND`; Postgres-swappable data layer (SQLAlchemy + Alembic, `DATABASE_URL` switches engines — **avoid SQLite-only SQL**); fully containerized so a VPS move is restore-backup + `docker compose up`, no code changes.

- **Status refresh** is an APScheduler job (`services/scheduler.py`) that re-checks only `for_sale`/`pending` properties on a configurable cadence and appends a `StatusHistory` row only when status changes (append-only history).

- **Map/list share one endpoint**: `GET /properties` with `bbox` (map), sort/filter, `criterion[<id>]=<op>:<val>` filters, and rating thresholds; filters are persisted in the URL so views are shareable. See PLAN.md §5 for the full API surface.

## Ops constraints (boulder-server)

- Set a backend container `mem_limit` (~1g) so it can't starve the ~13 other containers (Home Assistant, scrypted) on the N5105 / 7.5 GB host.
- Keep ingestion on the **API**, not Playwright (RAM).
- **Do not enable Tailscale Funnel** while serving cached listing photos — private app only.
- Backups: `ops/backup.sh` (nightly) — consistent `sqlite3 .backup` snapshot, then `restic` to **both** the Boulder and SF Synology NAS units (3-2-1), with `forget --prune` retention.

# home-search — Implementation Plan

A personal system for finding a second home: search an area against flexible
criteria, view promotional material, tag and rate properties, track status,
upload your own photos/videos/notes, view homes on a map and as a list, and
compute distances to amenities (grocery, cafe, restaurants, downtown).

Backend + web front-end now; iOS app later. Used by 2–3 people, ~50 properties
over time.

---

## 1. Decisions (settled)

| Area | Decision |
|---|---|
| **Stack** | FastAPI + SQLAlchemy + Alembic + SQLite (backend), React + Vite (web). Mirrors the `tracker` project. |
| **Repo** | Monorepo: `backend/`, `frontend/`, `ios/` (later), `docs/`, `ops/`. |
| **Auth** | JWT, 2–3 named users (you + wife + optional). |
| **Hosting (now)** | `boulder-server` (Ubuntu, Celeron N5105, 7.5 GB RAM, 62 GB free), Docker Compose, reached over Tailscale. |
| **Standby** | `sf-server` as warm standby (staged compose + latest restored backup). |
| **Backups** | Nightly `restic` (consistent SQLite snapshot + media) to **both** the Boulder and SF Synology NAS units. 3-2-1. |
| **Listing ingestion** | RapidAPI Zillow wrapper (`zillow-com1`) as primary — paste-URL + area search. Free 100 req/mo → $25/mo (10k). Redfin CSV for bulk seeding. Manual entry always available. |
| **Maps / distances** | Google Maps Platform (Maps JavaScript, Places, Distance Matrix). API key in `.env`. Results cached. |
| **Criteria** | Flexible, **typed** criteria — boolean / number(+unit) / rating-scale / enum / text — split into objective (shared) vs subjective (per-user). |
| **Caching** | Store every raw API response; download promo photos locally; cache distances; scheduled, bounded status refresh. |
| **Portability** | First-class: env-var config, storage abstraction (local → S3-compatible), Postgres-swappable data layer, fully containerized. Lift to a VPS with `docker compose up` + restored backup. |

---

## 2. Architecture

```
                         Tailscale (MagicDNS: home-search.<tailnet>.ts.net)
                                        │
                 ┌──────────────────────┴───────────────────────┐
                 │              boulder-server (Docker)          │
                 │                                               │
   browser/phone │   ┌──────────┐    ┌───────────┐              │
   ───────────────►  │ frontend │───►│  backend  │              │
                 │   │  (Vite)  │    │ (FastAPI) │              │
                 │   └──────────┘    └─────┬─────┘              │
                 │                         │                     │
                 │            ┌────────────┼────────────┐        │
                 │            ▼            ▼             ▼        │
                 │      ┌─────────┐  ┌──────────┐  ┌─────────┐  │
                 │      │ SQLite  │  │  media/  │  │ APsched │  │
                 │      │  .db    │  │ (volume) │  │ (status │  │
                 │      └─────────┘  └──────────┘  │ refresh)│  │
                 │                                 └─────────┘  │
                 └───────────────────────────────────────────────┘
                         │                       │
              external APIs (server-side):       │ nightly restic
              • Zillow (RapidAPI)                 ▼
              • Google Maps Platform        Boulder Synology + SF Synology
```

All third-party API calls are made **server-side** (keys never reach the
browser; responses are cached in the DB).

---

## 3. Repository layout (monorepo)

```
home-search/
├── README.md
├── CLAUDE.md
├── PLAN.md                       # this file
├── docker-compose.yml
├── .env.example
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic/                  # migrations
│   └── app/
│       ├── main.py               # FastAPI app + router includes
│       ├── config.py             # pydantic-settings (all env-driven)
│       ├── database.py           # engine/session (SQLite now, PG-swappable)
│       ├── models.py             # SQLAlchemy ORM
│       ├── schemas.py            # Pydantic request/response
│       ├── auth.py               # JWT (from tracker)
│       ├── routers/
│       │   ├── properties.py
│       │   ├── media.py
│       │   ├── criteria.py       # criteria definitions + values + ratings
│       │   ├── tags.py
│       │   ├── places.py         # amenity distances, POIs
│       │   └── ingest.py         # Zillow URL/area, Redfin CSV
│       └── services/
│           ├── zillow.py         # RapidAPI client + response cache
│           ├── redfin_csv.py     # CSV import
│           ├── maps.py           # geocode / places / distance matrix + cache
│           ├── storage.py        # media storage abstraction (local | s3)
│           └── scheduler.py      # APScheduler status-refresh job
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── api/                  # typed fetch client (from OpenAPI)
│       ├── pages/                # List, Map, Detail, Criteria admin, Login
│       └── components/           # FilterBar, RatingEditor, MediaGallery, …
├── ios/                          # added later; self-contained for clean extraction
└── ops/
    ├── backup.sh                 # consistent SQLite snapshot + restic to both NAS
    └── restic.env.example
```

---

## 4. Data model

Design goals: **flexible typed criteria**, full **caching** of external data, and
**portability**. Common listing fields are first-class columns (fast to query
and filter); everything bespoke lives in the criteria system or JSON.

### Core entities

**User** — `id, email, name, hashed_password, created_at`

**Property**
- `id, created_at, updated_at`
- Source/cache: `source` (zillow|redfin|manual), `source_url`, `source_id`
  (e.g. zpid), `raw_payload` (JSON — full cached API response), `last_synced_at`
- Location: `address, city, state, zip, county, latitude, longitude`
- Listing facts: `price, beds, baths, sqft, lot_size, year_built, property_type`
- `status` (for_sale | pending | sold | off_market | coming_soon), `days_on_market`
- `description` (promo text)
- `archived` (bool) — hide without deleting

**StatusHistory** — `id, property_id, status, observed_at, source`
Append-only; the scheduler writes a row only when status changes.

**Media** — `id, property_id, kind (photo|video|doc), origin (promo|upload),
storage_key, caption, uploaded_by, created_at`
`storage_key` resolves through the storage abstraction (local path or S3 object).
Promo photos are **downloaded and stored locally** so they persist even if the
listing is pulled, and to keep the app private (no hotlinking).

**Tag** + **PropertyTag** (m2m) — `Tag(id, name, color)` — freeform labels.

**Note** — `id, property_id, user_id, body, created_at` — multiple timestamped
notes per property, per user.

**PointOfInterest** — `id, user_id, name, latitude, longitude` — fixed places
you care about (your primary home, an office) for drive-time computation.

**PlaceDistance** — cached amenity results:
`id, property_id, category (grocery|cafe|restaurant|downtown|poi:<id>),
place_name, place_address, distance_meters, duration_seconds, mode
(driving|walking), computed_at, raw (JSON)`

### Flexible typed criteria (the core of the rating/attribute system)

A **single criteria system** covers both objective facts ("has a vineyard?",
"lot size in acres", "# olive trees", "ADU?") and subjective opinions ("feel of
the house", "proximity to neighbors"). The difference is the `is_subjective`
flag, which decides whether a value is shared per-property or recorded per-user.

**Criterion** — the definition (add/edit anytime, no code change)
- `id, name, description`
- `value_type` — `boolean | number | rating | enum | text`
- `unit` (nullable) — e.g. `acres`, `trees`, `min` (for number types)
- `scale_min, scale_max` (for `rating`, e.g. 1–5)
- `options` (JSON list, for `enum`)
- `is_subjective` (bool) — false = objective fact (one shared value); true =
  per-user opinion
- `weight` (float) — contribution to the weighted overall score
- `sort_order, active`

**CriterionValue** — one unified table for all values
- `id, property_id, criterion_id`
- `user_id` (nullable) — `NULL`/sentinel `0` = objective/shared; set = that user's
  subjective rating
- typed columns: `value_number` (REAL), `value_bool` (INT), `value_text` (TEXT)
  — the column used is determined by the criterion's `value_type`
  (`rating` is stored in `value_number`)
- `note, updated_at`
- Unique index on `(property_id, criterion_id, COALESCE(user_id, 0))`
  (SQLite treats NULLs as distinct, so we coalesce to a sentinel)

Examples:
| Criterion | value_type | unit | is_subjective | stored as |
|---|---|---|---|---|
| Vineyard? | boolean | — | no | `value_bool` |
| Olive trees | number | trees | no | `value_number` |
| ADU? | boolean | — | no | `value_bool` |
| Lot size | number | acres | no | `value_number` |
| Roof type | enum | — | no | `value_text` (one of `options`) |
| Feel of the house | rating | — | **yes** | `value_number` (1–5), per user |
| Proximity to neighbors | rating | — | **yes** | `value_number`, per user |

**Scoring.** A property's overall score = weighted average of its subjective
ratings (normalized to each criterion's scale), computed per-user and combined.
Objective booleans/numbers don't score but drive **filters**.

**Why this shape:** new criteria are pure data (insert a `Criterion` row);
filtering is a typed `JOIN` on `CriterionValue`; objective vs subjective is one
flag; and it's all standard SQL that ports cleanly to Postgres later.

---

## 5. API surface (REST/JSON, OpenAPI auto-generated)

```
POST   /auth/login                       → JWT
GET    /properties                       ?status=&min_price=&beds=&tags=
                                          &criterion[<id>]=<op>:<val>&sort=&bbox=
GET    /properties/{id}
POST   /properties                       (manual create)
PATCH  /properties/{id}                  (edit fields, status, archive)
GET    /properties/{id}/status-history

POST   /ingest/zillow/url                {url}          → fetch+cache+create
POST   /ingest/zillow/search             {area, filters}→ fetch+cache+create many
POST   /ingest/redfin/csv                (multipart)    → bulk import

GET    /media?property_id=               ; POST /media (upload) ; DELETE /media/{id}
GET    /media/{id}/file                  (streamed via storage abstraction)

GET    /criteria  ; POST /criteria ; PATCH /criteria/{id} ; DELETE /criteria/{id}
PUT    /properties/{id}/criteria/{cid}   (set objective value, or my rating)
GET    /properties/{id}/criteria         (values + my ratings + aggregates)

GET    /tags ; POST /tags ; PUT/DELETE …
PUT    /properties/{id}/tags

GET    /pois ; POST /pois
POST   /properties/{id}/distances/refresh   (compute via Google Maps, cache)
GET    /properties/{id}/distances
```

The map view fetches via a bounding-box (`bbox`) query; the list view uses the
same endpoint with sort/filter params, including `criterion[<id>]` filters and
rating thresholds.

---

## 6. Ingestion & caching strategy (keep API cost ~$0)

- **Cache everything.** Every Zillow/Maps response is stored (`raw_payload`,
  `PlaceDistance.raw`). The app reads from the DB; it only calls an API on
  explicit add or a scheduled refresh.
- **Promo photos downloaded locally** on import → persist + private + offline.
- **Status refresh** (APScheduler): a weekly (configurable) job re-checks only
  `for_sale`/`pending` properties, writes `StatusHistory` only on change.
  ~50 properties × weekly ≈ a couple hundred calls/month worst case — inside the
  free 100/mo if cadence is biweekly, otherwise comfortably inside the $25 tier.
- **Redfin CSV** import for seeding a whole target area at once, free.
- **Manual entry** form is always available and is the **graceful fallback** if
  an API call fails or returns thin data (pre-filled with whatever we got).

---

## 7. Maps & distances

- **Map view:** Google Maps JavaScript API; pins colored by `status`; clusters
  when zoomed out; click → detail. Filter changes re-query by `bbox`.
- **Distances:** per property, Places Nearby finds the closest grocery / cafe /
  restaurant / downtown (and any user `PointOfInterest`); Distance Matrix gives
  driving (and walking) time/distance. Cached in `PlaceDistance`, recomputed
  only on demand or when an address changes.
- **Filters:** "≤ 10 min to grocery", "≤ 20 min drive to <POI>", etc.

---

## 8. Frontend (React/Vite)

- **List view** — sortable/filterable table: price, beds/baths, sqft, status,
  tags, **overall rating**, per-criterion values, distance thresholds.
- **Map view** — same filter bar, pins by status, click-through to detail.
- **Detail page** — promo gallery (cached photos/video) + your uploads + notes +
  status timeline + the criteria panel (objective values + your rating sliders,
  with the combined household score) + computed distances.
- **Criteria admin** — add/edit/reorder criteria, set type/unit/scale/weight.
- **Filter bar** — composable filters incl. criterion-based, persisted in URL so
  views are shareable/bookmarkable.

---

## 9. Deployment (boulder-server, over Tailscale)

- `docker-compose.yml` modeled on `tracker`: `backend` + `frontend` services,
  named volumes for the SQLite DB and the `media/` directory.
- Bind to the host's Tailscale interface; access via MagicDNS
  (`home-search.<tailnet>.ts.net`). No public exposure; **don't** enable
  Tailscale Funnel while serving cached listing photos.
- **Memory limit** on the backend container (e.g. `mem_limit: 1g`) so it can
  never starve Home Assistant / scrypted / the other ~13 containers.
- Keep ingestion on the **API**, not Playwright, to respect the N5105's RAM.

---

## 10. Backups & standby

- `ops/backup.sh` (cron/systemd timer, nightly):
  1. `sqlite3 app.db ".backup snapshot.db"` (consistent, no torn copy)
  2. `restic backup snapshot.db media/` → **Boulder Synology** (SFTP)
  3. same → **SF Synology** (SFTP, over Tailscale)
  4. `restic forget --prune` retention (e.g. 7 daily / 4 weekly / 6 monthly)
- **sf-server**: compose file staged; recovery = `restic restore latest` +
  `docker compose up` (minutes, not a rebuild).

---

## 11. Portability to a hosted server (built in)

- **All config via env vars** (`config.py` / pydantic-settings) — no hardcoded
  paths, hostnames, or Tailscale IPs.
- **Storage abstraction** (`services/storage.py`): `local` driver now; `s3`
  driver (any S3-compatible bucket) selectable by `STORAGE_BACKEND=s3` + creds.
  Media keys are backend-agnostic.
- **Data layer Postgres-swappable**: SQLAlchemy + Alembic; avoid SQLite-only SQL.
  `DATABASE_URL` switches engines; migrations already in place.
- **Fully containerized**: moving to a VPS = point DNS / reverse proxy (Caddy for
  auto-HTTPS), `restic restore`, `docker compose up`. No code changes.

---

## 12. Build phases

0. **Scaffold** — monorepo, backend skeleton, `database.py`/`models.py`, JWT auth,
   Alembic, Docker Compose, `.env.example`, `CLAUDE.md`.
1. **Properties core** — manual CRUD, status + `StatusHistory`, tags, notes,
   **list view** with filters/sort.
2. **Media + map** — upload (storage abstraction), promo media model, detail page,
   **map view** (Google Maps JS).
3. **Flexible criteria** — `Criterion` + `CriterionValue`, criteria admin UI,
   objective values + per-user ratings, weighted score, filter by criteria.
4. **Ingestion + caching** — Zillow URL + area search, response caching, photo
   download, Redfin CSV import, scheduled status refresh.
5. **Distances** — Places + Distance Matrix, POIs, caching, distance filters.
6. **Ops** — `backup.sh` + restic to both Synologies, deploy to boulder-server,
   memory limits, sf-server standby.
7. **Later** — iOS app (SwiftUI) against the same API, Swift client generated from
   the OpenAPI spec.

---

## 13. Costs (steady state)

| Item | Cost |
|---|---|
| Zillow (RapidAPI) | $0 (free 100/mo) likely; $25/mo if exceeded |
| Google Maps Platform | $0 (free tier covers personal use) |
| Hosting | $0 (boulder-server) |
| Backups | $0 (existing Synologies) |
| **Total** | **~$0/mo**, ceiling ~$25/mo |

---

## 14. Open items / risks

- **Zillow wrapper is an unofficial scraper** — acceptable for a private app;
  keep it off the public internet. RentCast ($74/mo, cleaner license, no photos)
  is a fallback if the wrapper degrades.
- **Video storage growth** — media dir is relocatable (external drive / Synology /
  S3) via one setting if 62 GB gets tight.
- **Google Maps key** — you'll create a Maps Platform project + key (Maps JS,
  Places, Distance Matrix) before phase 5.
- **API key for RapidAPI** — free account before phase 4.

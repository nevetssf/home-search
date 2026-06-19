#!/usr/bin/env bash
# Run the full home-search stack for local development:
#   ./dev.sh [-o|--open]
#
# Starts the FastAPI backend (http://localhost:8000, docs at /docs) and the
# Vite frontend (http://localhost:3000, which proxies /api -> backend). It
# creates the backend venv and installs deps on first run (and re-installs when
# requirements.txt / package.json change), applies DB migrations, then runs
# both servers. Ctrl+C stops both.
#
#   -o, --open   open the app in your browser once the frontend is ready
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
VENV="$BACKEND/.venv"
FRONTEND_URL="http://localhost:3000"

log() { printf '\033[1;36m[dev]\033[0m %s\n' "$*"; }

OPEN_BROWSER=false
for arg in "$@"; do
  case "$arg" in
    -o|--open) OPEN_BROWSER=true ;;
    -h|--help) sed -n '2,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) log "Unknown option: $arg (use --help)"; exit 2 ;;
  esac
done

# Open the app in the default browser once the frontend answers (cross-platform).
open_when_ready() {
  for _ in $(seq 1 60); do
    curl -s -o /dev/null "$FRONTEND_URL/" 2>/dev/null && break
    sleep 0.5
  done
  if command -v open >/dev/null 2>&1; then open "$FRONTEND_URL"          # macOS
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$FRONTEND_URL"  # Linux
  else log "Open $FRONTEND_URL in your browser."; fi
}

# ── Backend setup ────────────────────────────────────────────────────────────
if [[ ! -d "$VENV" ]]; then
  log "Creating backend virtualenv…"
  python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

# (Re)install deps only when requirements.txt is newer than the last install.
STAMP="$VENV/.deps-installed"
if [[ ! -f "$STAMP" || "$BACKEND/requirements.txt" -nt "$STAMP" ]]; then
  log "Installing backend dependencies…"
  pip install -q --upgrade pip
  pip install -q -r "$BACKEND/requirements.txt"
  touch "$STAMP"
fi

log "Applying database migrations…"
# A DB first created by the app's init_db() (create_all) has the full schema but
# no recorded Alembic revision, so `upgrade` would try to recreate tables and
# fail with "table already exists". If the schema exists but Alembic has no
# current revision, stamp it at head so `upgrade` reconciles (and applies any
# future migrations) instead of recreating.
(cd "$BACKEND" && python - <<'PY'
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect
from app.database import engine

tables = set(inspect(engine).get_table_names())
with engine.connect() as conn:
    current = MigrationContext.configure(conn).get_current_revision()
if "properties" in tables and current is None:
    command.stamp(Config("alembic.ini"), "head")
    print("[dev] reconciled pre-existing DB: stamped at head")
PY
alembic upgrade head)

# Friendly nudge if no users exist yet (auth-gated routes need one).
if (cd "$BACKEND" && python -c "
from app.database import SessionLocal
from app.models import User
import sys
sys.exit(0 if SessionLocal().query(User).count() else 1)
" 2>/dev/null); then :; else
  log "No users yet — create one with:"
  log "    (cd backend && source .venv/bin/activate && python seed_user.py you@example.com \"Your Name\" <password>)"
fi

# ── Frontend setup ───────────────────────────────────────────────────────────
if [[ ! -d "$FRONTEND/node_modules" || "$FRONTEND/package.json" -nt "$FRONTEND/node_modules" ]]; then
  log "Installing frontend dependencies…"
  (cd "$FRONTEND" && npm install)
fi

# ── Run both, clean up on exit ───────────────────────────────────────────────
# Both servers run in THIS script's process group (no `set -m`), so a terminal
# Ctrl+C — which signals the whole foreground group — already reaches uvicorn
# (and its --reload worker child) and Vite directly. The trap additionally
# SIGTERMs each server's process tree, covering the SIGTERM/EXIT (non-Ctrl+C)
# case where children don't get the signal for free.
PIDS=()
kill_tree() {
  local pid=$1 child
  for child in $(pgrep -P "$pid" 2>/dev/null); do kill_tree "$child"; done
  kill -TERM "$pid" 2>/dev/null || true
}
cleanup() {
  trap - INT TERM EXIT  # avoid re-entry
  log "Shutting down…"
  for pid in "${PIDS[@]:-}"; do
    [[ -n "$pid" ]] && kill_tree "$pid"
  done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

log "Starting backend on http://localhost:8000  (docs: /docs)"
(cd "$BACKEND" && exec uvicorn app.main:app --reload --host 0.0.0.0 --port 8000) &
PIDS+=($!)

log "Starting frontend on http://localhost:3000"
(cd "$FRONTEND" && exec npm run dev) &
PIDS+=($!)

if $OPEN_BROWSER; then
  log "Will open $FRONTEND_URL when ready…"
  open_when_ready &  # in this process group, so cleanup reaps it too
fi

log "Both running. Press Ctrl+C to stop."
# Block until interrupted. Plain `wait` for portability — macOS ships bash 3.2,
# where `wait -n` is unsupported.
wait || true

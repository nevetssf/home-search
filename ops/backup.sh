#!/usr/bin/env bash
# Nightly backup for home-search (PLAN.md §10): consistent SQLite snapshot +
# media, pushed via restic to BOTH the Boulder and SF Synology NAS units (3-2-1).
#
# Run from a cron/systemd timer on boulder-server. Reads config from
# ops/restic.env (copy ops/restic.env.example). Safe to run while the app is up:
# the .backup command takes a consistent snapshot without a torn copy.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${RESTIC_ENV_FILE:-$SCRIPT_DIR/restic.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE (copy restic.env.example and fill it in)." >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$ENV_FILE"

: "${DB_PATH:?set DB_PATH in restic.env}"
: "${MEDIA_PATH:?set MEDIA_PATH in restic.env}"
: "${RESTIC_PASSWORD:?set RESTIC_PASSWORD in restic.env}"
: "${BOULDER_REPO:?set BOULDER_REPO in restic.env}"
: "${SF_REPO:?set SF_REPO in restic.env}"

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
SNAPSHOT="$WORKDIR/snapshot.db"

echo "[backup] taking consistent SQLite snapshot…"
sqlite3 "$DB_PATH" ".backup '$SNAPSHOT'"

# Retention: 7 daily / 4 weekly / 6 monthly.
FORGET_ARGS=(--keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune)

backup_to() {
  local repo="$1" label="$2"
  echo "[backup] → $label ($repo)"
  export RESTIC_REPOSITORY="$repo"
  # Initialize the repo on first run (no-op if it already exists).
  restic snapshots >/dev/null 2>&1 || restic init
  restic backup "$SNAPSHOT" "$MEDIA_PATH" --tag home-search
  restic forget "${FORGET_ARGS[@]}" --tag home-search
}

backup_to "$BOULDER_REPO" "Boulder Synology"
backup_to "$SF_REPO" "SF Synology"

echo "[backup] done."

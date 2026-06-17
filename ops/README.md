# Ops — deploy, backup, standby (PLAN.md §9, §10)

## Deploy to boulder-server

Private app over Tailscale — **never enable Tailscale Funnel** while serving
cached listing photos.

```bash
git clone <repo> /srv/home-search && cd /srv/home-search
cp .env.example .env            # set JWT_SECRET_KEY, RAPIDAPI_KEY, GOOGLE_MAPS_API_KEY
docker compose up -d --build
# Bootstrap the first household user (others are added in-app):
docker compose exec backend python seed_user.py you@example.com "Your Name" <password>
```

Reach it at `http://home-search.<tailnet>.ts.net:3000` (frontend) → it talks to
the backend on `:8000`. The backend container has `mem_limit: 1g` so it can't
starve Home Assistant / scrypted / the other ~13 containers on the N5105.

Migrations run automatically on container start (`alembic upgrade head` in the
backend `CMD`).

## Backups

`ops/backup.sh` takes a consistent SQLite snapshot and pushes it + the media
dir via restic to **both** Synology NAS units (3-2-1). Configure it:

```bash
cp ops/restic.env.example ops/restic.env   # fill in repos, password, paths
./ops/backup.sh                              # test run
```

Schedule nightly with the included systemd timer:

```bash
sudo cp ops/home-search-backup.service ops/home-search-backup.timer /etc/systemd/system/
sudo systemctl enable --now home-search-backup.timer
```

## SF-server standby

Stage the same compose file on `sf-server`. Recovery is minutes, not a rebuild:

```bash
RESTIC_REPOSITORY=$SF_REPO restic restore latest --target /srv/home-search/data
docker compose up -d
```

## Restore a single file locally

```bash
RESTIC_REPOSITORY=$BOULDER_REPO restic snapshots
RESTIC_REPOSITORY=$BOULDER_REPO restic restore <id> --target ./restored
```

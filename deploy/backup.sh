#!/bin/sh
# Run from the repository directory with its deployment .env.
# Source XLSX files and database are backed up while application writers are stopped.
set -eu
backup_root=${1:-./backups}
mkdir -p "$backup_root"
backup_stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_path="$backup_root/$backup_stamp"
mkdir -m 700 "$backup_path"
umask 077
restart_app() { docker compose start web worker >/dev/null; }
docker compose stop web worker
trap restart_app EXIT HUP INT TERM
docker compose exec -T db pg_dump -U scheduler -d scheduler -Fc > "$backup_path/database.dump"
docker compose run --rm --no-deps -T --entrypoint tar web -C /app/data -czf - . > "$backup_path/uploads.tar.gz"
date -u > "$backup_path/created.txt"
printf 'Backup saved: %s\n' "$backup_path"

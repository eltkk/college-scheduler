#!/bin/sh
# Destructive operation: explicit --replace-current is mandatory.
set -eu
if [ "$#" -ne 2 ] || [ "$2" != "--replace-current" ]; then
  printf 'Usage: %s BACKUP_DIRECTORY --replace-current\n' "$0" >&2
  exit 2
fi
backup_path=$1
test -s "$backup_path/database.dump"
test -s "$backup_path/uploads.tar.gz"
docker compose stop web worker
docker compose exec -T db pg_restore -U scheduler -d scheduler --clean --if-exists --no-owner --exit-on-error < "$backup_path/database.dump"
docker compose run --rm --no-deps -T --entrypoint python web -c 'from pathlib import Path; import shutil; p=Path("/app/data"); [(shutil.rmtree(x) if x.is_dir() else x.unlink()) for x in p.iterdir()]'
docker compose run --rm --no-deps -T --entrypoint tar web -C /app/data -xzf - < "$backup_path/uploads.tar.gz"
docker compose start web worker
printf 'Restore complete. Check login, state and original XLSX files.\n'

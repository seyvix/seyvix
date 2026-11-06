#!/usr/bin/env bash
# Back up the database, uploaded files (local storage volume) and .env.
#
# Usage: scripts/backup.sh [backups-root]        (default: ./backups)
# Env:   BACKUP_KEEP_DAYS=14                      delete backups older than this
#
# Result: <backups-root>/<UTC timestamp>/{db.dump,storage.tar.gz,env}
# The database is dumped first: files added afterwards are harmless orphans that the
# maintenance job removes, while the reverse order could reference missing files.
# The stack keeps running; pg_dump takes a consistent snapshot.
set -euo pipefail
cd "$(dirname "$0")/.."

root=${1:-backups}
keep_days=${BACKUP_KEEP_DAYS:-14}
stamp=$(date -u +%Y%m%dT%H%M%SZ)
dest="$root/$stamp"
partial="$dest.partial"

umask 077
mkdir -p "$partial"
trap 'rm -rf "$partial"' ERR

echo "backup: database"
docker compose exec -T postgres sh -c \
  'pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom --no-owner' \
  >"$partial/db.dump"

storage_backend=$(sed -n 's/^STORAGE_BACKEND=//p' .env | tail -n 1)
if [[ ${storage_backend:-local} == local ]]; then
  echo "backup: files"
  docker compose run --rm --no-deps -T api tar -C /data/content -cf - . | gzip -1 \
    >"$partial/storage.tar.gz"
else
  echo "backup: STORAGE_BACKEND=$storage_backend - back up the bucket with your provider's tools"
fi

cp .env "$partial/env"
mv "$partial" "$dest"
trap - ERR
echo "backup: $dest ($(du -sh "$dest" | cut -f1))"

find "$root" -mindepth 1 -maxdepth 1 -type d -mtime +"$keep_days" -print -exec rm -rf {} +

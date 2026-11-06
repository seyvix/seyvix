#!/usr/bin/env bash
# Restore a backup made by scripts/backup.sh. DESTROYS the current database and files.
#
# Usage: scripts/restore.sh <backup-dir> [--yes]
#
# .env is NOT overwritten; compare it with <backup-dir>/env yourself (AUTH_JWT_SECRET
# change only logs users out; AI_EMBEDDING_DIMENSIONS must match the dumped schema).
set -euo pipefail
cd "$(dirname "$0")/.."

src=${1:?usage: scripts/restore.sh <backup-dir> [--yes]}
[[ -f $src/db.dump ]] || { echo "restore: $src/db.dump not found" >&2; exit 1; }

if [[ ${2:-} != --yes ]]; then
  read -r -p "Replace the current database and files with $src? Type 'yes': " answer
  [[ $answer == yes ]] || { echo "aborted"; exit 1; }
fi

echo "restore: stopping application services"
# shellcheck disable=SC2046 # service names never contain spaces
docker compose stop $(docker compose config --services | grep -vx postgres)
docker compose up -d --wait postgres

echo "restore: database"
docker compose exec -T postgres sh -c '
  set -e
  dropdb --username="$POSTGRES_USER" --if-exists --force "$POSTGRES_DB"
  createdb --username="$POSTGRES_USER" --owner="$POSTGRES_USER" "$POSTGRES_DB"
  pg_restore --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --no-owner --exit-on-error
' <"$src/db.dump"

if [[ -f $src/storage.tar.gz ]]; then
  echo "restore: files"
  docker compose run --rm --no-deps -T api sh -c \
    'find /data/content -mindepth 1 -delete && tar -C /data/content -xzf -' \
    <"$src/storage.tar.gz"
fi

echo "restore: starting stack"
docker compose up -d --no-build --wait
echo "restore: done"

#!/usr/bin/env bash
# Deploy (or roll back to) a published image tag. Runs on the server inside the deploy dir.
#
# Usage: scripts/deploy.sh <image-tag> [image-prefix]
#   image-tag     git sha published by CI (see .deploy-history for previous ones)
#   image-prefix  e.g. ghcr.io/owner/seyvix; stored in .env as IMAGE_PREFIX
# If REGISTRY_USER is set, the registry password/token is read from stdin and the
# credentials are removed again after pulling.
#
# The tag is recorded in .env (IMAGE_TAG) so plain `docker compose ...` commands keep
# using the deployed images. The last 3 deployed tags stay on disk for fast rollback.
set -euo pipefail
cd "$(dirname "$0")/.."

tag=${1:?usage: scripts/deploy.sh <image-tag> [image-prefix]}
prefix=${2:-}
keep_tags=3

die() { echo "deploy: $*" >&2; exit 1; }
[[ -f .env ]] || die "missing $(pwd)/.env (see README: deploy to server)"
[[ $tag =~ ^[A-Za-z0-9._-]+$ ]] || die "invalid image tag: $tag"

exec 9>.deploy.lock
flock -n 9 || die "another deploy is running"

env_get() { sed -n "s/^$1=//p" .env | tail -n 1; }
env_set() {
  if grep -q "^$1=" .env; then
    sed -i "s|^$1=.*|$1=$2|" .env
  else
    printf '%s=%s\n' "$1" "$2" >>.env
  fi
}

if [[ -n $prefix ]]; then
  [[ $prefix =~ ^[a-z0-9./_-]+$ ]] || die "invalid image prefix: $prefix"
  env_set IMAGE_PREFIX "$prefix"
fi
prefix=$(env_get IMAGE_PREFIX)
[[ -n $prefix ]] || die "IMAGE_PREFIX is not set (pass it as the 2nd argument once)"

if [[ -n ${REGISTRY_USER:-} ]]; then
  registry=${prefix%%/*}
  docker login "$registry" --username "$REGISTRY_USER" --password-stdin >/dev/null
  trap 'docker logout "$registry" >/dev/null 2>&1' EXIT
fi

export IMAGE_TAG=$tag
echo "deploy: pulling $prefix/*:$tag"
docker compose pull --quiet
if [[ -n ${registry:-} ]]; then
  docker logout "$registry" >/dev/null
  trap - EXIT
fi

env_set IMAGE_TAG "$tag"
printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$tag" >>.deploy-history

echo "deploy: starting stack"
if ! docker compose up -d --no-build --remove-orphans --wait --wait-timeout 300; then
  docker compose ps --all
  die "stack is not healthy; inspect with 'docker compose logs <service>' and roll back with 'scripts/deploy.sh <previous-tag>' (see .deploy-history)"
fi

# Free disk: dangling layers plus our images older than the last $keep_tags deploys.
docker image prune --force >/dev/null
recent=$(awk '{print $2}' .deploy-history | tail -n 50 | tac | awk '!seen[$0]++' | head -n "$keep_tags")
docker image ls --format '{{.Repository}}:{{.Tag}}' | while read -r ref; do
  [[ $ref == "$prefix"/* ]] || continue
  grep -qxF "${ref##*:}" <<<"$recent" && continue
  docker image rm "$ref" >/dev/null || echo "deploy: kept $ref (still referenced)"
done

docker compose ps
echo "deploy: $tag is live"

#!/usr/bin/env bash
# Create .env from .env.example with freshly generated secrets.
# Usage: scripts/init-env.sh            (refuses to overwrite an existing .env)
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -e .env ]]; then
  echo ".env already exists; edit it by hand or remove it first" >&2
  exit 1
fi
command -v openssl >/dev/null || { echo "openssl is required" >&2; exit 1; }

secret() { openssl rand -hex 32; }

umask 077
sed \
  -e "s|^POSTGRES_PASSWORD=$|POSTGRES_PASSWORD=$(secret)|" \
  -e "s|^AUTH_JWT_SECRET=$|AUTH_JWT_SECRET=$(secret)|" \
  -e "s|^TELEGRAM_INTERNAL_TOKEN=$|TELEGRAM_INTERNAL_TOKEN=$(secret)|" \
  .env.example > .env

echo "Created .env with generated secrets. Now set at least:"
echo "  SITE_ADDRESS, PUBLIC_URL, ADMIN_TELEGRAM_IDS, TELEGRAM_BOT_TOKEN (and AI_API_KEY if wanted)"

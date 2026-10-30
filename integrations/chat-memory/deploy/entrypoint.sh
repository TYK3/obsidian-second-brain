#!/bin/sh
# Required env: VAULT_REPO (e.g. TYK3/second-brain-vault), GITHUB_TOKEN (fine-grained, Contents: read/write
# on that one repo), SECOND_BRAIN_TOKEN (the connector secret, >= 24 chars).
# Optional: READ_ONLY=1, GIT_SYNC_MINUTES (default 5).
set -e
: "${VAULT_REPO:?set VAULT_REPO}" "${GITHUB_TOKEN:?set GITHUB_TOKEN}" "${SECOND_BRAIN_TOKEN:?set SECOND_BRAIN_TOKEN}"
VAULT=/data/vault
if [ ! -d "$VAULT/.git" ]; then
  mkdir -p /data
  git clone -q "https://x-access-token:${GITHUB_TOKEN}@github.com/${VAULT_REPO}.git" "$VAULT"
fi
cd "$VAULT"
git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/${VAULT_REPO}.git"
git config user.name  "second-brain server"
git config user.email "second-brain@localhost"
git pull -q --rebase --autostash || true
export SECOND_BRAIN_VAULT="$VAULT"
brain init --no-git >/dev/null
brain reindex >/dev/null
RO=""; [ "${READ_ONLY:-0}" = "1" ] && RO="--read-only"
exec brain serve --host 0.0.0.0 --port "${PORT:-8765}" --git-sync "${GIT_SYNC_MINUTES:-5}" $RO

#!/usr/bin/env bash
# Canonical one-command deploy for the Chess app (GreatReads rebuild pattern).
# Data is safe: SQLite lives in the bind-mounted ./data, never in the image.
set -euo pipefail

cd "$(dirname "$0")/.."

BUILD_STAMP=$(date '+%Y-%m-%d %H:%M')
BUILD_DIRTY=$(git status --porcelain 2>/dev/null | grep -q . && echo "M" || echo "")

echo "Rebuilding chess_app (${BUILD_STAMP}${BUILD_DIRTY:+ ${BUILD_DIRTY}})..."
BUILD_STAMP="$BUILD_STAMP" BUILD_DIRTY="$BUILD_DIRTY" \
    docker compose up -d --build

echo -n "Waiting for health"
for _ in $(seq 1 30); do
    status=$(docker inspect chess_app --format '{{.State.Health.Status}}' 2>/dev/null || echo starting)
    [ "$status" = "healthy" ] && { echo " → healthy"; exit 0; }
    [ "$status" = "unhealthy" ] && { echo " → UNHEALTHY"; docker logs chess_app --tail 20; exit 1; }
    echo -n "."
    sleep 2
done
echo " → timed out"; exit 1

#!/usr/bin/env bash
# Nightly chess.com sync, run by Dagu (#28): ssh dockerhost '~/projects/Chess/scripts/nightly-sync.sh'
# Syncs the root player first, then everyone /api/v1/sync/targets lists, one at a
# time (chess.com wants serial requests). Exits non-zero if any player failed.
set -uo pipefail

BASE="${CHESS_URL:-http://localhost:8011}"
ROOT="${1:-}"

targets=$(curl -fsS "$BASE/api/v1/sync/targets${ROOT:+?player=$ROOT}") || {
    echo "could not fetch sync targets from $BASE"; exit 1; }

failed=0
while IFS=$'\t' read -r player reason; do
    echo "== $player ($reason)"
    if ! curl -fsS -X POST "$BASE/api/v1/sync?player=$player"; then
        echo "!! sync failed for $player"
        failed=$((failed + 1))
    fi
    echo
done < <(python3 -c 'import json,sys
for t in json.load(sys.stdin)["targets"]: print(t["player"], t["reason"], sep="\t")' <<<"$targets")

[ "$failed" -eq 0 ] || { echo "$failed player(s) failed"; exit 1; }

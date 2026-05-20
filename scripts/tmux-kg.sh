#!/usr/bin/env bash
# Start or attach tmux session for KG stack (compose logs + Cloudflare Quick Tunnel).
# Usage: ./scripts/tmux-kg.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION="${KG_TMUX_SESSION:-kg}"
TUNNEL_TARGET="${TUNNEL_TARGET:-http://127.0.0.1:5001}"
CF_BIN="${CLOUDFLARED_BIN:-cloudflared}"

cd "$ROOT"

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux not installed."
  exit 1
fi

if ! command -v "$CF_BIN" >/dev/null 2>&1; then
  echo "cloudflared not found (set CLOUDFLARED_BIN)."
  exit 1
fi

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "Session '$SESSION' already running. Attach: tmux attach -t $SESSION"
  exec tmux attach -t "$SESSION"
fi

tmux new-session -d -s "$SESSION" -n status -c "$ROOT"
tmux send-keys -t "${SESSION}:status" \
  "echo 'KG stack | UI http://127.0.0.1:5001 | Neo4j http://127.0.0.1:7474'" C-m
tmux send-keys -t "${SESSION}:status" "docker compose ps" C-m

tmux new-window -t "$SESSION" -n logs -c "$ROOT"
tmux send-keys -t "${SESSION}:logs" "docker compose logs -f --tail=200" C-m

tmux new-window -t "$SESSION" -n tunnel -c "$ROOT"
tmux send-keys -t "${SESSION}:tunnel" \
  "echo 'Quick Tunnel -> ${TUNNEL_TARGET}'" C-m
tmux send-keys -t "${SESSION}:tunnel" \
  "$CF_BIN tunnel --url ${TUNNEL_TARGET}" C-m

tmux select-window -t "${SESSION}:tunnel"
echo "Started tmux session '$SESSION'."
echo "  attach: tmux attach -t $SESSION"
echo "  tunnel URL: see window 'tunnel' (https://....trycloudflare.com)"
exec tmux attach -t "$SESSION"

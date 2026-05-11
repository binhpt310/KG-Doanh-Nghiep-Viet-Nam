#!/usr/bin/env bash
# Interactive helper: Docker Compose + Cloudflare Quick Tunnel for this repo.
# Run from repo root: ./manage.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

COMPOSE=(docker compose)
TUNNEL_TARGET="${TUNNEL_TARGET:-http://127.0.0.1:5001}"
STATE_DIR="$ROOT/.dev"
PID_FILE="$STATE_DIR/cloudflared.pid"
LOG_FILE="$STATE_DIR/cloudflared.log"
URL_FILE="$STATE_DIR/tunnel.url"

mkdir -p "$STATE_DIR"

# Prefer cloudflared on PATH; allow override.
CF_BIN="${CLOUDFLARED_BIN:-cloudflared}"

port_listening() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -tln 2>/dev/null | grep -q ":${port} "
    return $?
  fi
  if command -v nc >/dev/null 2>&1; then
    nc -z 127.0.0.1 "$port" 2>/dev/null
    return $?
  fi
  return 1
}

http_ok() {
  local url="$1"
  command -v curl >/dev/null 2>&1 && curl -fsS -o /dev/null --max-time 3 "$url" 2>/dev/null
}

compose_ps() {
  "${COMPOSE[@]}" ps -a 2>/dev/null || true
}

tunnel_running() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null
}

tunnel_stop() {
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 0.5
    fi
    rm -f "$PID_FILE"
  fi
  rm -f "$URL_FILE"
  echo "Tunnel stopped."
}

tunnel_extract_url() {
  # cloudflared prints a trycloudflare.com URL on stderr/stdout
  grep -oE 'https://[a-zA-Z0-9.-]+\.trycloudflare\.com' | head -1
}

tunnel_start() {
  if ! command -v "$CF_BIN" >/dev/null 2>&1; then
    echo "cloudflared not found. Install it or set CLOUDFLARED_BIN to the binary path."
    echo "Example: wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 && chmod +x cloudflared-linux-amd64"
    return 1
  fi
  tunnel_stop
  echo "Starting Quick Tunnel -> $TUNNEL_TARGET (logging to $LOG_FILE)"
  rm -f "$LOG_FILE"
  # Run in background; parse URL after a short wait
  nohup "$CF_BIN" tunnel --url "$TUNNEL_TARGET" >>"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"
  local waited=0
  local url=""
  while [[ "$waited" -lt 25 ]]; do
    if [[ -f "$LOG_FILE" ]]; then
      url="$(tunnel_extract_url <"$LOG_FILE" || true)"
      [[ -n "$url" ]] && break
    fi
    sleep 1
    waited=$((waited + 1))
  done
  if [[ -n "$url" ]]; then
    echo "$url" >"$URL_FILE"
    echo "Tunnel URL: $url"
  else
    echo "Tunnel started (pid $(cat "$PID_FILE")) but URL not parsed yet. Check: tail -f $LOG_FILE"
  fi
}

print_status() {
  echo "=== Compose ==="
  compose_ps
  echo ""
  echo "=== Ports (host) ==="
  for p in 5001 5002 7474 7687; do
    if port_listening "$p"; then
      echo "  $p: listening"
    else
      echo "  $p: closed"
    fi
  done
  echo ""
  echo "=== HTTP checks ==="
  if http_ok "http://127.0.0.1:5001/"; then
    echo "  http://127.0.0.1:5001/ OK (kg-ui / nginx)"
  else
    echo "  http://127.0.0.1:5001/ not reachable"
  fi
  if http_ok "http://127.0.0.1:5002/api/stats" || http_ok "http://127.0.0.1:5002/"; then
    echo "  http://127.0.0.1:5002/ OK (kg-app Flask on host map)"
  else
    echo "  http://127.0.0.1:5002/ not reachable (expected only if kg-app published)"
  fi
  echo ""
  echo "=== Cloudflare Quick Tunnel ==="
  if tunnel_running; then
    echo "  Process: running (pid $(cat "$PID_FILE"))"
    if [[ -f "$URL_FILE" ]]; then
      echo "  URL: $(cat "$URL_FILE")"
    else
      echo "  URL: (parse log) tail -20 $LOG_FILE"
    fi
  else
    echo "  Not running"
  fi
}

menu() {
  echo ""
  echo "KG stack — pick an action"
  echo "  1) Status"
  echo "  2) Start stack (docker compose up -d --build)"
  echo "  3) Restart stack"
  echo "  4) Stop stack (docker compose down)"
  echo "  5) Logs (pick service)"
  echo "  6) Start Quick Tunnel (5001)"
  echo "  7) Stop Quick Tunnel"
  echo "  8) Show tunnel URL"
  echo "  9) Open local UI in browser (xdg-open)"
  echo "  0) Exit"
  echo -n "> "
}

logs_menu() {
  echo "Services: neo4j | kg-app | kg-ui | all"
  read -r -p "Service name: " svc
  case "$svc" in
    neo4j|kg-app|kg-ui) "${COMPOSE[@]}" logs -f --tail=200 "$svc" ;;
    all) "${COMPOSE[@]}" logs -f --tail=100 ;;
    *) echo "Unknown service";;
  esac
}

while true; do
  menu
  read -r choice || exit 0
  case "$choice" in
    1) print_status ;;
    2) "${COMPOSE[@]}" up -d --build && print_status ;;
    3) "${COMPOSE[@]}" up -d --build --force-recreate && print_status ;;
    4) "${COMPOSE[@]}" down && tunnel_stop ;;
    5) logs_menu ;;
    6) tunnel_start ;;
    7) tunnel_stop ;;
    8)
      if [[ -f "$URL_FILE" ]]; then cat "$URL_FILE"; else tail -30 "$LOG_FILE" 2>/dev/null || echo "No tunnel log"; fi
      ;;
    9)
      if command -v xdg-open >/dev/null 2>&1; then xdg-open "http://127.0.0.1:5001/" 2>/dev/null || true
      elif command -v open >/dev/null 2>&1; then open "http://127.0.0.1:5001/" 2>/dev/null || true
      else echo "Open http://127.0.0.1:5001/ in your browser"; fi
      ;;
    0|q|Q) exit 0 ;;
    *) echo "Invalid option";;
  esac
done

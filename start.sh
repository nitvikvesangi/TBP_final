#!/usr/bin/env bash
#
# One command: start the receiver, wait until it answers, open the live dashboard.
#
#   ./start.sh              start (or reuse) the receiver and open the dashboard
#   ./start.sh --status     is it up? where? how many records?
#   ./start.sh --stop       stop the receiver started by this script
#   ./start.sh --restart    stop, then start
#   ./start.sh --port 9000  use another port
#   ./start.sh --foreground stay in this terminal, Ctrl-C to stop (no PID file)
#   NO_OPEN=1 ./start.sh    do not open a browser
#
# The token and the port come from secrets.h (CLOUD_TOKEN / CLOUD_URL), so the
# laptop and the board cannot drift apart: one file drives both.

set -euo pipefail
cd "$(dirname "$0")"
ROOT=$(pwd)

PIDFILE="$ROOT/server/.receiver.pid"
LOGFILE="$ROOT/server/receiver.log"
EVENTS="$ROOT/server/data/events.ndjson"
PY=python3

PORT=8080
PORT_SET=0
ACTION=start
DO_OPEN=1
[ -n "${NO_OPEN:-}" ] && DO_OPEN=0

die() { printf '  ! %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --stop)    ACTION=stop ;;
    --status)  ACTION=status ;;
    --restart) ACTION=restart ;;
    --start)   ACTION=start ;;
    --foreground|--fg) ACTION=foreground ;;
    --no-open) DO_OPEN=0 ;;
    --port)    shift; [ $# -gt 0 ] || die "--port needs a number"; PORT=$1; PORT_SET=1 ;;
    --port=*)  PORT=${1#*=}; PORT_SET=1 ;;
    -h|--help) sed -n '2,16p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)         die "unknown option: $1  (try --help)" ;;
  esac
  shift
done

command -v "$PY" >/dev/null 2>&1 || die "$PY not found - install Python 3 first"
[ -f "$ROOT/server/server.py" ] || die "server/server.py is missing"

# ---- settings from secrets.h (never printed in full) -------------------------
cdefine() {
  [ -f "$ROOT/secrets.h" ] || return 0
  sed -nE "s/^[[:space:]]*#[[:space:]]*define[[:space:]]+$1[[:space:]]+\"(.*)\".*/\1/p" \
    "$ROOT/secrets.h" | head -1
}

TOKEN=$(cdefine CLOUD_TOKEN || true)
CLOUD_URL=$(cdefine CLOUD_URL || true)

if [ "$PORT_SET" -eq 0 ] && [ -n "$CLOUD_URL" ]; then
  from_url=$(printf '%s' "$CLOUD_URL" | sed -nE 's#^[a-zA-Z]+://[^/:]+:([0-9]+).*#\1#p')
  [ -n "$from_url" ] && PORT=$from_url
fi

lan_ip() {
  "$PY" - <<'PY' 2>/dev/null || echo 127.0.0.1
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(("8.8.8.8", 80))   # no packet is sent
    print(s.getsockname()[0])
except OSError:
    print("127.0.0.1")
finally:
    s.close()
PY
}

LOCAL_URL="http://127.0.0.1:$PORT/"
LAN_URL="http://$(lan_ip):$PORT/"

# ---- process helpers ---------------------------------------------------------
running_pid() {
  [ -f "$PIDFILE" ] || return 1
  local pid
  pid=$(cat "$PIDFILE" 2>/dev/null || true)
  case "$pid" in ''|*[!0-9]*) return 1 ;; esac
  kill -0 "$pid" 2>/dev/null || return 1
  ps -p "$pid" -o command= 2>/dev/null | grep -q "server/server.py" || return 1
  printf '%s' "$pid"
}

healthy() {
  "$PY" - "$PORT" <<'PY' >/dev/null 2>&1
import sys, urllib.request
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/health", timeout=2) as r:
        sys.exit(0 if r.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
}

port_owner() { lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null | head -1 || true; }

open_dashboard() {
  [ "$DO_OPEN" -eq 1 ] || { printf '  dashboard  : %s\n' "$LOCAL_URL"; return 0; }
  printf '  dashboard  : %s  (opening)\n' "$LOCAL_URL"
  if command -v open >/dev/null 2>&1; then open "$LOCAL_URL" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$LOCAL_URL" >/dev/null 2>&1 || true
  fi
}

stop_server() {
  local pid
  if ! pid=$(running_pid); then
    rm -f "$PIDFILE"
    printf '  not running (nothing to stop)\n'
    return 0
  fi
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 50); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.1
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" 2>/dev/null || true
    printf '  ! pid %s ignored SIGTERM, killed it\n' "$pid"
  else
    printf '  stopped pid %s\n' "$pid"
  fi
  rm -f "$PIDFILE"
}

warn_url_mismatch() {
  [ -n "$CLOUD_URL" ] || return 0
  local host
  host=$(printf '%s' "$CLOUD_URL" | sed -nE 's#^[a-zA-Z]+://([^/:]+).*#\1#p')
  [ -n "$host" ] || return 0
  if [ "$host" != "$(lan_ip)" ]; then
    printf '\n  ! the board is told to upload to %s\n' "$host"
    printf '    this laptop is now at %s\n' "$(lan_ip)"
    printf '    Wi-Fi changed? set CLOUD_URL in secrets.h and re-upload the sketch,\n'
    printf '    otherwise scans stay on the board and the dashboard stays still.\n'
  fi
}

status_server() {
  local pid
  if pid=$(running_pid); then
    if healthy; then
      printf '  running    : pid %s, /health 200\n' "$pid"
    else
      printf '  running    : pid %s, but /health did not answer (see %s)\n' "$pid" "${LOGFILE#$ROOT/}"
    fi
    printf '  dashboard  : %s\n' "$LOCAL_URL"
    printf '  on the LAN : %s\n' "$LAN_URL"
  else
    local owner
    owner=$(port_owner)
    if [ -n "$owner" ] && healthy; then
      printf '  running    : pid %s on port %s, started outside this script\n' "$owner" "$PORT"
      printf '               (Ctrl-C in its terminal to stop it; ./start.sh --stop will not touch it)\n'
      printf '  dashboard  : %s\n' "$LOCAL_URL"
    else
      printf '  not running\n'
      return 1
    fi
  fi
  if [ -f "$EVENTS" ]; then
    local n last
    n=$(wc -l <"$EVENTS" | tr -d ' ')
    last=$("$PY" - "$EVENTS" <<'PY' 2>/dev/null || true
import json, sys
rows = [l for l in open(sys.argv[1]) if l.strip()]
if rows:
    r = json.loads(rows[-1])
    print(f"{r.get('ts','?')}  {r.get('roll') or r.get('uid')}  {r.get('result')}  {r.get('attendance')}")
PY
)
    printf '  records    : %s in server/data/events.ndjson\n' "$n"
    [ -n "$last" ] && printf '  last       : %s\n' "$last"
  else
    printf '  records    : none yet (server/data/events.ndjson will be created)\n'
  fi
  return 0
}

start_server() {
  local pid
  if pid=$(running_pid); then
    printf '  already up : pid %s\n' "$pid"
    healthy || printf '  ! but /health did not answer - try ./start.sh --restart\n'
    open_dashboard
    return 0
  fi

  local owner
  owner=$(port_owner)
  if [ -n "$owner" ]; then
    # A receiver started by hand on this port is fine - adopt it instead of
    # fighting over the socket, so the demo only ever needs one command.
    if healthy && ps -p "$owner" -o command= 2>/dev/null | grep -q "server/server.py"; then
      echo "$owner" >"$PIDFILE"
      printf '  already up : pid %s on port %s (reusing the receiver you started)\n' "$owner" "$PORT"
      open_dashboard
      return 0
    fi
    die "port $PORT is already used by pid $owner. ./start.sh --port 8081, or stop that process."
  fi

  mkdir -p "$(dirname "$LOGFILE")"
  printf '\n  starting   : %s server/server.py --port %s\n' "$PY" "$PORT"
  if [ -n "$TOKEN" ]; then
    nohup "$PY" -u "$ROOT/server/server.py" --port "$PORT" --token "$TOKEN" >>"$LOGFILE" 2>&1 &
  else
    nohup "$PY" -u "$ROOT/server/server.py" --port "$PORT" >>"$LOGFILE" 2>&1 &
  fi
  echo $! >"$PIDFILE"

  for _ in $(seq 1 60); do
    if healthy; then break; fi
    kill -0 "$(cat "$PIDFILE")" 2>/dev/null || break
    sleep 0.25
  done

  if ! healthy; then
    printf '\n  ! the server did not answer on port %s\n' "$PORT" >&2
    printf '    last lines of %s:\n' "${LOGFILE#$ROOT/}" >&2
    tail -n 15 "$LOGFILE" 2>/dev/null | sed 's/^/    | /' >&2 || true
    rm -f "$PIDFILE"
    exit 1
  fi

  printf '  pid        : %s   log: %s\n' "$(cat "$PIDFILE")" "${LOGFILE#$ROOT/}"
  printf '  token      : %s\n' "$([ -n "$TOKEN" ] && echo 'set (from secrets.h)' || echo 'open - no token')"
  open_dashboard
  printf '  on the LAN : %s\n' "$LAN_URL"
  warn_url_mismatch
  printf '\n  board alone (no laptop, no server) still:\n'
  printf '    - reads cards, opens the door, lights green/red\n'
  printf '    - remembers attendance in flash, prints it over serial\n'
  printf '    - keeps scans queued to send when the server is back\n'
  printf '  the live dashboard needs this script running.\n'
  printf '\n  stop with ./start.sh --stop   check with ./start.sh --status\n\n'
}

foreground_server() {
  local owner
  owner=$(port_owner)
  if [ -n "$owner" ]; then
    die "port $PORT is already used by pid $owner - use ./start.sh --status, or --stop that one first"
  fi
  printf '\n  dashboard  : %s\n' "$LOCAL_URL"
  printf '  on the LAN : %s\n' "$LAN_URL"
  printf '  token      : %s\n' "$([ -n "$TOKEN" ] && echo 'set (from secrets.h)' || echo 'open - no token')"
  printf '  Ctrl-C stops it. The dashboard needs this window open.\n\n'
  warn_url_mismatch
  if [ -n "$TOKEN" ]; then
    exec "$PY" -u "$ROOT/server/server.py" --port "$PORT" --token "$TOKEN"
  else
    exec "$PY" -u "$ROOT/server/server.py" --port "$PORT"
  fi
}

case "$ACTION" in
  stop)       stop_server ;;
  status)     status_server ;;
  restart)    stop_server; printf '\n'; start_server ;;
  foreground) foreground_server ;;
  start)      start_server ;;
esac

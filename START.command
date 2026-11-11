#!/bin/bash
#
# START — the whole demo, one double-click.
#
#   Double-click this file in Finder (or drag it to the Dock), and it will:
#     1. find the board on USB
#     2. make sure the firmware uploads to THIS laptop's current Wi-Fi address,
#        and re-flash only if it drifted (a new network changes the IP)
#     3. start the receiver and open the live dashboard
#     4. print the board's own status: wifi, roster, queue
#
#   Options (for scripting):  --dry-run   say what it would do, change nothing
#                             --no-flash  never re-flash, just warn
#   Env: NO_OPEN=1 (don't launch a browser)  PAUSE=0 (don't wait for a key)
#        SECRETS=/path/other.h (use another secrets file, for testing)
#
# Stop later with STOP.command, or ./start.sh --stop

set -uo pipefail
cd "$(dirname "$0")" || exit 1
ROOT=$(pwd)

SECRETS=${SECRETS:-"$ROOT/secrets.h"}
ESP_PY=/tmp/espvenv/bin/python
PORT_NUM=8080
DRY=0
ALLOW_FLASH=1
DO_OPEN=1
PAUSE=${PAUSE:-1}
[ -n "${NO_OPEN:-}" ] && DO_OPEN=0

for arg in "$@"; do
  case "$arg" in
    --dry-run)  DRY=1 ;;
    --no-flash) ALLOW_FLASH=0 ;;
    --no-open)  DO_OPEN=0 ;;
    -h|--help)  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) printf '  ! unknown option: %s\n' "$arg"; exit 2 ;;
  esac
done

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
say()  { printf '  %s\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }

# ---- 1. the board -----------------------------------------------------------
find_port() {
  local c
  for c in /dev/cu.usbserial-* /dev/cu.wchusbserial* /dev/cu.SLAB_USBtoUART*; do
    [ -e "$c" ] && { printf '%s' "$c"; return 0; }
  done
  return 1
}

lan_ip() {
  python3 - <<'PY' 2>/dev/null || echo 127.0.0.1
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(("8.8.8.8", 80))    # no packet is sent
    print(s.getsockname()[0])
except OSError:
    print("127.0.0.1")
finally:
    s.close()
PY
}

bold "RFID attendance + door access"
echo
PORT=$(find_port || true)
IP=$(lan_ip)

if [ -n "$PORT" ]; then
  ok "board found on $PORT"
else
  warn "no board on USB — the dashboard will start, but nothing will scan"
fi
ok "this laptop is at $IP"

# ---- 2. keep the firmware pointed at this laptop ----------------------------
old_url=$(sed -nE 's/^[[:space:]]*#[[:space:]]*define[[:space:]]+CLOUD_URL[[:space:]]+"([^"]*)".*/\1/p' "$SECRETS" 2>/dev/null | head -1)
url_port=$(printf '%s' "$old_url" | sed -nE 's#^[a-z]+://[^/:]+:([0-9]+).*#\1#p')
url_port=${url_port:-8080}
url_path=$(printf '%s' "$old_url" | sed -E 's#^[a-z]+://[^/]+##')
url_path=${url_path:-/api/scan}
old_host=$(printf '%s' "$old_url" | sed -nE 's#^[a-z]+://([^/:]+).*#\1#p')
PORT_NUM=$url_port
new_url="http://$IP:$url_port$url_path"

if [ -z "$old_url" ]; then
  warn "no CLOUD_URL in ${SECRETS#$ROOT/} — the board will not upload"
elif [ "$old_host" = "$IP" ]; then
  ok "firmware target matches: $new_url"
else
  warn "firmware still points at $old_host, laptop is now $IP"
  if [ "$DRY" -eq 1 ]; then
    say "would set CLOUD_URL to $new_url and re-flash"
  elif [ -z "$PORT" ]; then
    warn "connect the board and run START again to fix this"
  else
    # note the '|' delimiter: the pattern itself contains '#' (for #define),
    # so '#' cannot be the s/// separator
    tmp=$(mktemp)
    sed -E "s|^([[:space:]]*#[[:space:]]*define[[:space:]]+CLOUD_URL[[:space:]]+)\"[^\"]*\"|\\1\"$new_url\"|" \
      "$SECRETS" >"$tmp" && cat "$tmp" >"$SECRETS" && rm -f "$tmp"
    ok "updated CLOUD_URL in ${SECRETS#$ROOT/}: $new_url"
    if [ "$ALLOW_FLASH" -eq 0 ]; then
      warn "not re-flashing (--no-flash) — the board keeps the old address until you flash"
    else
    say "re-flashing so the board uses it (about a minute)…"
    if PORT="$PORT" ./scripts/flash.sh 2>&1 | sed 's/^/     /'; then
      ok "board re-flashed and rebooted"
    else
      bad "flash failed — secrets.h is updated, the board still has the old address"
      say "try again, or hold BOOT while replugging if it will not enter the bootloader"
    fi
    fi
  fi
fi

# ---- 3. the receiver + dashboard -------------------------------------------
echo
bold "Starting the receiver"
if [ "$DRY" -eq 1 ]; then
  say "would start the receiver and open http://127.0.0.1:$PORT_NUM/"
elif NO_OPEN=1 ./start.sh; then
  :
else
  bad "the receiver did not start — see server/receiver.log"
  [ "$PAUSE" = 0 ] || { echo; read -n 1 -s -r -p "Press any key to close"; echo; }
  exit 1
fi

if [ "$DO_OPEN" -eq 1 ] && [ "$DRY" -eq 0 ]; then
  open "http://127.0.0.1:$PORT_NUM/" >/dev/null 2>&1 && ok "dashboard opened in your browser"
fi

# ---- 4. the board's own status ---------------------------------------------
if [ -n "$PORT" ] && [ "$DRY" -eq 0 ]; then
  echo
  bold "Board status"
  [ -x "$ESP_PY" ] || ESP_PY=python3
  if "$ESP_PY" scripts/serial_send.py "wifi" "queue" "list" 2>/dev/null \
       | sed 's/\r//g' | grep -v '^[[:space:]]*$' | sed 's/^/  /' | head -20; then
    :
  else
    warn "could not read the board (the port may be busy) — its banner is on USB anyway"
  fi
fi

echo
bold "Ready"
say "dashboard : http://127.0.0.1:$PORT_NUM/   (LAN: http://$IP:$PORT_NUM/)"
say "tap a card: green + servo nudge = granted, red = not in the roster"
say "stop      : double-click STOP.command"
echo
[ "$PAUSE" = 0 ] || { read -n 1 -s -r -p "Press any key to close this window"; echo; }

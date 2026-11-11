#!/usr/bin/env bash
#
# Flash the whole firmware on this Mac and prove it booted.
#
#   ./scripts/flash.sh              wait for the board, compile, flash, read the banner
#   PORT=/dev/cu.wchusbserial123 ./scripts/flash.sh
#   SKIP_READ=1 ./scripts/flash.sh  flash only
#
# Why this exists: esptool and the Arduino IDE both die on this Mac with
#   termios.error: (22, 'Invalid argument')
# because the system USB-serial driver rejects tcsetattr. scripts/esp_patch.py
# sets the baud with the IOSSIOSPEED ioctl instead, and this script always goes
# through it - `arduino-cli upload` never works here, `arduino-cli compile` does.
#
# It writes all four images (bootloader, partition table, boot_app0, app), which
# is what repairs a board stuck in a boot loop after a partial write. The app
# goes to 0x10000 and nothing touches 0x290000, so the roster and the queued
# scans in LittleFS survive.

set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

FQBN=esp32:esp32:esp32
BAUD=${BAUD:-115200}
BUILD=${BUILD:-/tmp/flash_build}
STAGE=${STAGE:-/tmp/flash_sketch/rfid-attendance-door}
VENV=${VENV:-/tmp/espvenv}
PY="$VENV/bin/python"

say() { printf '  %s\n' "$*"; }
die() { printf '  ! %s\n' "$*" >&2; exit 1; }

[ -f "$ROOT/rfid-attendance-door.ino" ] || die "run this from the project folder"

# ---- python env with pyserial + esptool --------------------------------------
if [ ! -x "$PY" ]; then
  say "creating $VENV (pyserial + esptool)"
  python3 -m venv "$VENV" || die "could not create a venv"
  "$VENV/bin/pip" install --quiet --disable-pip-version-check pyserial esptool \
    || die "pip install failed"
fi
"$PY" -c "import serial, esptool" 2>/dev/null || die "$VENV is missing pyserial/esptool"

# ---- the board ---------------------------------------------------------------
PORT=${PORT:-}
case "$PORT" in /dev/*) ;; *) PORT="" ;; esac
if [ -z "$PORT" ]; then
  say "waiting for the board on USB (plug it in with a data cable)..."
  for _ in $(seq 1 40); do
    for c in /dev/cu.usbserial-* /dev/cu.wchusbserial* /dev/cu.SLAB_USBtoUART*; do
      [ -e "$c" ] && { PORT=$c; break; }
    done
    [ -n "$PORT" ] && break
    sleep 3
  done
  [ -n "$PORT" ] || die "no serial port after 2 minutes - check the cable is a data cable, then replug"
fi

if [ ! -e "$PORT" ]; then
  die "$PORT does not exist"
fi

HOLDER=$(lsof -t "$PORT" 2>/dev/null || true)
if [ -n "$HOLDER" ]; then
  die "$PORT is held by pid $HOLDER - close the Serial Monitor or run: kill $HOLDER"
fi

say "port: $PORT"

# ---- compile ----------------------------------------------------------------
rm -rf "$BUILD" "$STAGE"
# arduino-cli insists the sketch folder be named after the .ino, and this
# project folder is often a copy ("... copy"), so compile from a staged copy.
mkdir -p "$STAGE"
cp "$ROOT/rfid-attendance-door.ino" "$STAGE/"
[ -f "$ROOT/secrets.h" ] && cp "$ROOT/secrets.h" "$STAGE/"
for f in "$ROOT"/*.h; do [ -f "$f" ] && cp "$f" "$STAGE/"; done
say "compiling $FQBN"
./.tools/arduino-cli compile --fqbn "$FQBN" --board-options FlashMode=dio \
    --build-path "$BUILD" "$STAGE" 2>&1 | tail -3 \
  || die "compile failed"
APP="$BUILD/rfid-attendance-door.ino.bin"
BL="$BUILD/rfid-attendance-door.ino.bootloader.bin"
PT="$BUILD/rfid-attendance-door.ino.partitions.bin"
BA="$BUILD/boot_app0.bin"
for f in "$APP" "$BL" "$PT" "$BA"; do [ -f "$f" ] || die "missing build output: $f"; done
say "app: $(wc -c <"$APP" | tr -d ' ') bytes"

# ---- flash ------------------------------------------------------------------
say "flashing (bootloader, partitions, boot_app0, app at 0x10000)"
PYTHONPATH=scripts "$PY" scripts/run_esptool.py \
  --port "$PORT" --baud "$BAUD" --chip esp32 \
  write_flash --flash_mode dio --flash_freq 40m --flash_size 4MB \
  0x1000 "$BL" \
  0x8000 "$PT" \
  0xe000 "$BA" \
  0x10000 "$APP" 2>&1 | grep -E "Wrote|Hash|Writing at 0x00010000|Leaving|Hard reset|error|A fatal" \
  || die "flash failed - try again with BAUD=460800, or hold BOOT while replugging"

say "flashed"

# ---- prove it ---------------------------------------------------------------
if [ -z "${SKIP_READ:-}" ]; then
  sleep 3
  say "reading the boot banner for 15 s"
  OUT=$("$PY" scripts/serial_read.py 15 2>/dev/null | sed 's/\r//g' | grep -v '^$' || true)
  printf '%s\n' "$OUT" | sed 's/^/    | /'
  echo
  if printf '%s' "$OUT" | grep -q "System Ready"; then
    say "BOOTED: found 'System Ready'"
    printf '%s' "$OUT" | grep -qE "rc522: ok" && say "reader: ok" || say "reader: NOT ok - check SPI wiring"
    printf '%s' "$OUT" | grep -E "roster:|wifi:|ip |ntp:|cloud url" | sed 's/^/    /' || true
    echo
    say "tap a card now - the console line is 'GRANTED/PRESENT' and the green LED flashes"
  else
    say "no 'System Ready' in that capture - tap reset, or run: $PY scripts/serial_read.py 15"
    exit 1
  fi
fi

# Host-side helpers

These exist because the Arduino IDE **cannot upload or read serial** on this Mac.

The system driver (`com.apple.DriverKit-AppleUSBSLCOM`) rejects every
`tcsetattr` call with `EINVAL`:

```
termios.error: (22, 'Invalid argument')   serialposix.py:517
```

pyserial uses `tcsetattr` to set the baud rate, so esptool crashes and the IDE's
Serial Monitor never opens. The workaround is to set the baud rate with the
`IOSSIOSPEED` ioctl (`0x80045402`) and skip `tcsetattr` entirely. Silicon Labs'
own macOS driver is x86_64-only, so it cannot be installed on Apple Silicon.

**Python env:** `/tmp/espvenv` (pyserial 3.5 + esptool 4.13). If `/tmp` was
cleaned, recreate it:

```bash
python3 -m venv /tmp/espvenv
/tmp/espvenv/bin/pip install pyserial esptool
```

**Port:** the scripts hard-code `/dev/cu.usbserial-0001`. Check with `ls /dev/cu.*`
and edit `P` in the relevant file if yours differs.

---

## Scripts

| Script | Purpose |
|---|---|
| `esp_patch.py` | monkeypatches `Serial._reconfigure_port` to use `IOSSIOSPEED`; imported, not run |
| `flash.sh` | the normal way to flash: waits for the port, compiles, writes bootloader + partitions + boot_app0 + app, prints the banner |
| `run_esptool.py` | imports the patch, then runs esptool as `__main__` |
| `serial_read.py` | capture N seconds of serial to stdout (`serial_read.py 10`) |
| `serial_live.py` | stream indefinitely, `Ctrl-C` to stop |
| `serial_send.py` | send one or more console commands and print the reply |
| `serial_persist.py` | long capture written straight to a file |
| `proxy_demo.py` | fires three different `sim` cards quickly to trigger proxy detection |

Only one process can hold the port. Free it first:

```bash
PIDS=$(lsof -t /dev/cu.usbserial-0001); [ -n "$PIDS" ] && kill $PIDS
```

Never use `pkill -f` — the pattern can match the agent's own command line.

---

## Usage

Flashing (always `PYTHONPATH=scripts` so `esp_patch` is importable):

```bash
PYTHONPATH=scripts /tmp/espvenv/bin/python scripts/run_esptool.py \
    --port /dev/cu.usbserial-0001 --baud 115200 --chip esp32 \
    write_flash --flash_mode dio --flash_freq 40m \
    0x10000 /tmp/main_dio/rfid-attendance-door.ino.bin
```

That address matters: `0x10000` overwrites only the application, leaving the
LittleFS roster and attendance queue intact. A merged image at `0x0` wipes them.

Serial:

```bash
/tmp/espvenv/bin/python scripts/serial_read.py 10
/tmp/espvenv/bin/python scripts/serial_live.py
/tmp/espvenv/bin/python scripts/serial_send.py "list" "sim AA BB CC DD"
```

Because the IDE's Serial Monitor does not work here, the console is effectively
write-only for the user — commands have to be relayed through `serial_send.py`.

See `../HANDOFF.md` for the full environment picture.

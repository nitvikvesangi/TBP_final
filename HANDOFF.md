# HANDOFF — read this first

Everything a fresh session (or a different AI account) needs to continue this
project **without re-discovering the environment**. Written after the first
hardware bring-up session on **7 Nov 2026**.

If you are an AI agent picking this up cold: read this file, then `README.md`,
then `CHEATSHEET.md`. Do **not** re-install the ESP32 toolchain — it already
exists in `.tools/` (~7 GB, project-local).

---

## 1. Current board state (read before flashing anything)

| Item | State |
|---|---|
| Sketch **currently running** | `rfid-attendance-door.ino` — the real firmware, LEDs included |
| Project firmware on the board | **Yes** — app-only flash at `0x10000`, hash verified |
| Roster (registered cards) | **5 cards** in LittleFS `/roster.txt` — `CS-01` … `CS-05`. `CS-06` (`2E 63 64 F8`, the second personal card) is **deliberately unregistered**, so one physical card gives a real `DENIED` + red LED; `register 2E 63 64 F8 CS-06 Owner 2` puts it back. The NFC tag `04 11 22 33 44 55 66` is unregistered too |
| Attendance queue | Kept in LittleFS as well. Re-check with `queue` before a demo — anything pending uploads by itself once Wi-Fi is on |
| LEDs | **Working** — green 0.5 s pulse on grant, red 0.5 s on denial (see §6.1 for the cause) |
| Servo | **Nudge mode** — on a grant it gives two ~200 ms pulses then settles; the latch is **not** held open (see §6.10) |
| Wi-Fi / NTP | Configured during the 2026-11-08/09 sessions (records carry `"src":"ntp"`); with no network it falls back to `"src":"uptime"` and records queue in flash |
| USB | Connected as `/dev/cu.usbserial-0001`. If it vanishes, the cable is out — confirm with `ls /dev/cu.*` |

The roster survived several reflashes because it was only ever overwritten with
an **app-only flash at `0x10000`**, never a full erase. Keep doing that (see §4)
and the cards will keep surviving.

To reflash: compile, then write the app at `0x10000` — both exact commands are in
**§4**. Do not use a merged image at `0x0`; that wipes the roster.

**If a board boot-loops after an app-only flash** (`assert failed: __esp_system_init_fn_init_flash startup_funcs.c:118 (flash_ret == ESP_OK)`), the application header's flash configuration does not match the chip. Do not keep rewriting `0x10000` - run `./scripts/flash.sh`, which compiles into a clean directory and writes bootloader + partition table + boot_app0 + app with an explicit 4 MB size, then prints the banner so you can see `System Ready`. Never write the merged image at `0x0`: that erases the roster and the queued scans.

Confirm with `list` that 5 cards are present. If it shows 4 or the demo names
reappear, the flash erased LittleFS.

**Verified after removing CS-06** — `remove 2E 63 64 F8`, then `reboot`, then `list`,
so this is the state that survives a power cycle:

```
-- roster --
  01 02 03 04    CS-01 Alice Sharma     -
  11 22 33 44    CS-02 Rohit Verma      -
  55 66 77 88    CS-03 Sara Khan        -
  AA BB CC DD    CS-04 Imran Qureshi    -
  20 74 0B 56    CS-05 Owner            -
-- 0 of 5 present
```

---

## 2. Hardware as built

Verified working in this session unless marked otherwise.

### MFRC522 reader

| RC522 | ESP32 |
|---|---|
| SDA (SS) | GPIO 5 |
| SCK | GPIO 18 |
| MOSI | GPIO 23 |
| MISO | GPIO 19 |
| RST | **GPIO 22** (confirmed by the user) |
| 3.3V | 3V3 — **never 5 V** |
| GND | GND (blue rail) |
| IRQ | not connected |

**RST pin — settled: GPIO 22.** The firmware originally declared GPIO 21 while
the build sheet said `RST → P22`. The reader worked regardless because
`PCD_Init()` also issues a *software* reset, so the wire was never load-bearing
— which is why the mismatch stayed invisible for so long. The user confirmed the
wire is physically in **22**; `RST_PIN` was changed to 22, and after a reboot the
board still reports `rc522: ok (version 0x82)` and `roster: 5 cards`. Code,
`rc522_test/`, `README.md`, `REPORT.md` and this file now all say 22.

### SG90 servo

| Servo | Goes to |
|---|---|
| Brown (GND) | blue rail |
| Red/orange (V+) | red rail = ESP32 **5V** |
| Yellow (signal) | GPIO 13 |

470 µF electrolytic across the 5 V rail (long leg + to red, striped leg to
blue), **fitted**, close to the servo wires.

**Servo status: verified under load, and now in nudge mode** (§6.10) — the horn
gives two short pulses per grant instead of holding the latch open. Two runs of six back-to-back grants — one unloaded, one with the
horn held so it had to fight back — both finished with **zero reboots** and open
intervals of 4.9–5.1 s. A free-running SG90 draws ~100–200 mA against ~600–750 mA
stalled, so the loaded run is the meaningful one, and the rail held.

### Indicator LEDs (working — see §6.1 for the ground-rail cause)

| LED | ESP32 | Path |
|---|---|---|
| Green — granted / door open | GPIO 26 | pin → resistor → long leg; short leg → blue GND rail |
| Red — denied | GPIO 27 | same |

Both LEDs confirm the **scan**, not the door. `grantFlash()` drives green HIGH for
`LED_GRANT_MS` (500 ms); `denyFlash()` drives red HIGH for `LED_DENY_MS` (500 ms);
a non-blocking `serviceLeds()` in `loop()` clears each when its deadline passes.
Driving green from door state was tried and reverted — a 5 s lamp lets a queue
walk straight through and manufactures false proxy flags.

**Do not use** GPIO 6–11 (internal flash) or 16/17 (PSRAM on WROVER modules).

### Reader is a counterfeit chip

The module reports **firmware version 0x82** (`rc522: ok (version 0x82)`).
Genuine NXP MFRC522 reports 0x92. 0x82 is a common clone; it reads cards
correctly, so this is fine — but say so in the report rather than claiming
genuine hardware. `0x00` / `0xFF` means the SPI wiring is broken.

---

## 3. Environment landmines (this specific Mac)

**Machine:** macOS 26.5.1 arm64 · port `/dev/cu.usbserial-0001` (CP2102) ·
ESP32-D0WD-V3, 4 MB flash, MAC `4c:c3:82:f2:c0:c0`.

### 3.1 The Arduino IDE cannot upload or open Serial Monitor here

The system USB-serial driver (`com.apple.DriverKit-AppleUSBSLCOM`) rejects
**every** `tcsetattr` call with `EINVAL`, even when the settings are unchanged:

```
termios.error: (22, 'Invalid argument')   serialposix.py:517
```

That breaks pyserial (→ esptool → the IDE's Upload button) and the IDE's Serial
Monitor. **This is not a project bug and no amount of reinstalling fixes it.**
Silicon Labs' own macOS driver is x86_64-only and unusable on Apple Silicon.

**Workaround (already implemented in `scripts/`):** set the baud rate with the
`IOSSIOSPEED` ioctl (`0x80045402`) and never call `tcsetattr` at all.

- `scripts/esp_patch.py` — monkeypatches `serial.serialposix.Serial._reconfigure_port`
- `scripts/run_esptool.py` — imports that patch, then runs esptool
- `scripts/serial_*.py` — open the port with raw `os.open` + the ioctl

Python env with pyserial 3.5 + esptool 4.13: **`/tmp/espvenv`** (recreate with
`. .venv/bin/activate`-style install of `pyserial esptool` if `/tmp` was wiped).

Consequence for the user: **the serial console is write-only for them.** They
cannot type `register` / `list` / `sim` themselves — an agent must relay every
command via `scripts/serial_send.py`.

### 3.2 Flash mode must be DIO

The ESP32 Dev Module profile defaults to QIO. This board's flash chip doesn't
support it and boot-loops:

```
qio_mode: Failed to set QIE bit
assert failed: __esp_system_init_fn_init_flash startup_funcs.c:118
```

Always pass `--board-options FlashMode=dio` when compiling and
`--flash_mode dio` when flashing. Documented in `README.md` §2.

### 3.3 Toolchain location

- `.tools/arduino-cli`, `.tools/cli.yaml`, `.tools/.arduino15`, `.tools/.user`
- ESP32 core 3.3.12, libraries MFRC522 (Miguel Balboa) + ESP32Servo
- Arduino IDE **2.2.0** installed in `/Applications`; its
  `~/Library/Arduino15/arduino-cli.yaml` and `~/.arduinoIDE/arduino-cli.yaml`
  point at the `.tools/` dirs so the IDE compiles, but its Upload/Monitor are
  broken per §3.1.

---

## 4. Exact commands

Run from the project root.

### Free the serial port (something is holding it)

```bash
PIDS=$(lsof -t /dev/cu.usbserial-0001); [ -n "$PIDS" ] && kill $PIDS
```

Never use `pkill -f` / `pgrep -f | xargs kill` — the pattern can match the
agent's own command line and kill the session.

### Compile

```bash
./.tools/arduino-cli --config-file .tools/cli.yaml compile \
    --fqbn esp32:esp32:esp32 --board-options FlashMode=dio --output-dir /tmp/main_dio .
```

### Flash the app only — **preserves the roster and queue** (preferred)

```bash
PYTHONPATH=scripts /tmp/espvenv/bin/python scripts/run_esptool.py \
    --port /dev/cu.usbserial-0001 --baud 115200 --chip esp32 \
    write_flash --flash_mode dio --flash_freq 40m \
    0x10000 /tmp/main_dio/rfid-attendance-door.ino.bin
```

### Flash a whole merged image — **erases the roster**

```bash
PYTHONPATH=scripts /tmp/espvenv/bin/python scripts/run_esptool.py \
    --port /dev/cu.usbserial-0001 --baud 115200 --chip esp32 \
    write_flash --flash_mode dio --flash_freq 40m 0x0 <merged.bin>
```

Only do this after `erase_flash`, and expect to re-register every card.

### Serial

```bash
/tmp/espvenv/bin/python scripts/serial_read.py 10          # capture 10 s
/tmp/espvenv/bin/python scripts/serial_live.py             # stream until Ctrl-C
/tmp/espvenv/bin/python scripts/serial_send.py "list" "sim AA BB CC DD"
```

### Full wipe (loses cards, queue, session state)

```bash
PYTHONPATH=scripts /tmp/espvenv/bin/python scripts/run_esptool.py \
    --port /dev/cu.usbserial-0001 --baud 115200 --chip esp32 erase_flash
```

First boot after an erase prints `Corrupted dir pair` / `mount failed (-84)`
before `flash: ok`. That is a one-time LittleFS format, not a fault.

---

## 5. What was verified on real hardware

Evidence, not claims — all of this was observed on the board/serial output.

| Behaviour | Observed |
|---|---|
| Boot, reader detected | `rc522: ok (version 0x82)`, `flash: ok`, `roster: 4 cards` → then 6 |
| Real card tap opens door | `Owner CS-05 GRANTED PRESENT`, `"simulated":false`, `door: UNLOCKED` |
| No double counting | second tap → `GRANTED ALREADY_MARKED` |
| Auto-relock after 5 s | `door: LOCKED` |
| Unlock window never extended | taps at t=1.0/14.1/27.0 → locks at 6.0/19.1/32.0 s; a tap at t=6.0 **inside** the open window left the lock time unchanged (see §6.7) |
| Green LED | 0.5 s pulse per accepted scan, then dark while the door is still open |
| Red LED | 0.5 s flash on `sim DE AD BE EF` |
| Servo swing | horn moves to 90° on grant, back to 0° on lock |
| Servo under load | 6 loaded cycles with the horn gripped, 470 µF fitted → 0 reboots, 4.9–5.0 s opens |
| Polling survives servo movement | card polling suspended for `SERVO_SETTLE_MS` (300 ms) after each swing; 6 cycles still locked at 5.0–5.1 s, so the pause does not distort the window |
| Nudge mode, reads uninterrupted | grant at t=1.1 s → `DENIED` at t=2.2 s → grant at t=3.0 s, all three processed; `door: nudge` replaces `door: UNLOCKED` |
| Unknown card refused | `2E 63 64 F8` → `DENIED NOT_RECORDED`, door stayed locked |
| Accept **and** reject with real cards in one pass | T+80 `CS-05 GRANTED PRESENT` (green, servo swung), T+83 `2E 63 64 F8 DENIED NOT_RECORDED` (red, no servo); both `"simulated":false` |
| Live registration (no re-flash) | after `register`, same card → `GRANTED` |
| Roster persists across reboot | `reboot` → `roster: 5 cards` |
| Proxy detection | 3 distinct `sim` cards in ~3 s → `<<< PROXY SUSPECT`, `"suspect":true`, `!! 3 different cards tapped within 2s` (window tightened from 5 s, see §6.7) |
| Attendance tally | `list` → `5 of 6 present` |
| Offline queue | `queue: 10 pending` with no Wi-Fi |
| Firmware compile | 1 107 431 bytes (84 %), 52 252 bytes RAM (15 %) |
| Analysis test suite | 14/14 pass (`cd analysis && python3 -m unittest tests -v`) |

**Still unverified:** Wi-Fi upload and NTP timestamps; the live dashboard on
real data. (Servo, LEDs and the full card → door path are all confirmed.)

### Registered cards (placeholders — replace with real names)

**Both real cards are registered** (restored 2026-11-09): `register 2E 63 64 F8 CS-06 Owner 2`
was sent over serial and `list` now prints **6 cards**, CS-01 … CS-06 (CS-06 was removed again after the test — §1 has the current five). The card had
been left out for a while so the red LED and `DENIED` path could be demonstrated with
a real card — to do that again, `remove 2E 63 64 F8` and put it back the same way.
No re-flash is involved either way.

| UID | Roll | Name |
|---|---|---|
| `01 02 03 04` | CS-01 | Alice Sharma *(demo seed)* |
| `11 22 33 44` | CS-02 | Rohit Verma *(demo seed)* |
| `55 66 77 88` | CS-03 | Sara Khan *(demo seed)* |
| `AA BB CC DD` | CS-04 | Imran Qureshi *(demo seed)* |
| `20 74 0B 56` | CS-05 | **Owner** ← real card, placeholder name |
| `2E 63 64 F8` | CS-06 | **Owner 2** ← real card, placeholder name |

Rename with `remove <uid>` then `register <uid> <roll> <name>` — no re-flash
needed.

---

## 6. Open issues, in priority order

### 6.1 LEDs — RESOLVED: it was a split ground rail, not the resistor

The pins were never at fault: `led_test` read back `1` on GPIO 26 and 27 and the
onboard blue LED (GPIO 2) blinked, while the external LEDs stayed dark.

**Real cause:** the breadboard's blue ground rail is **not continuous** — it is
split at the halfway mark. The ESP32 GND sat on one half and the LEDs on the
other, so both LED legs were near 3.3 V and no current could flow.

**The measurement that settled it** (reuse this for any dead LED): meter on
**DCV 20**, black probe on the ESP32 GND pin, red probe on the LED's *short*
leg. Healthy = **0 V**. If it reads 3.3 V, the ground path is open and no
resistor change will ever matter. Buzzing the two far ends of the blue rail
confirms a split in one second.

**Fixed** by bridging the gap. Both LEDs then lit under `led_steady`, and with
the real firmware on the board:

| Command | Result | LED |
|---|---|---|
| `sim 20 74 0B 56` | `door: UNLOCKED`, `CS-05 GRANTED PRESENT` | green pulse, 0.5 s |
| `sim DE AD BE EF` | `door: stays LOCKED`, `DENIED NOT_RECORDED` | red, 0.5 s |

**A previous theory was wrong — do not revive it.** The series resistor was
blamed for being 61 kΩ from its colour bands. It measured `0.20` on the 2k range
(= **200 Ω**) and was correct all along. Two meter lessons from this session:

1. The continuity/buzzer position cannot measure a resistor — it shows `1` for
   anything over 2000 Ω, and a **buzz means the probes are shorted**, never that
   a resistor is low.
2. Colour bands lose to the meter. A 6-band part read in the wrong direction
   gives a plausible but badly wrong value.

Diagnostic sketches kept for reuse: `led_test/` (sweeps 26, 27, 25, 32, 33, 14,
4, 15, 2 one at a time, naming each pin) and `led_steady/` (holds 26 and 27 HIGH
forever, for calm multimeter probing).

### 6.2 RST pin — RESOLVED: GPIO 22 everywhere

The wiring was in **22** while the code drove **21**; it never showed up because
`PCD_Init()` resets the chip in software. `RST_PIN` is now **22** and the reader
re-verified after a reboot. See §2 for the full note.

### 6.3 Servo — RESOLVED: survives loaded movement

Two six-cycle runs of back-to-back grants, timing captured from serial:

| Run | Capacitor | Load | Reboots | Open intervals |
|---|---|---|---|---|
| Baseline | absent | none | **0** | 5.0 / 5.0 / 5.0 / 5.1 / 4.9 / 5.0 s |
| Loaded | 470 µF fitted | horn gripped | **0** | 5.0 / 5.0 / 4.9 / 5.0 / 5.0 / 5.0 s |

Nothing in the log differed between them — no `rst:0x…`, no boot banner, no
timing drift — so the regulator is not being pulled down even when the horn has
to push back.

**Caveat:** a hand grip is real resistance but not a hard stall. If the finished
latch ever jams the horn mid-travel, that is the case this test does not cover;
the fix then is an external 5 V supply for the servo with a common ground, with
the capacitor staying as the local buffer.

If movement is ever too short to release the latch, tune `SERVO_LOCKED` (0) and
`SERVO_UNLOCKED` (90) — those are guesses, not measured positions.

### 6.4 Wi-Fi, NTP and cloud upload never configured

`WIFI_SSID`, `WIFI_PASS`, `CLOUD_URL`, `CLOUD_TOKEN` are empty ⇒ offline mode.
To demo the full path: start `python3 server/server.py --token S3cret` on the
laptop sharing the hotspot, paste the printed upload URL into `CLOUD_URL`,
re-flash, then `upload`. 2.4 GHz only; iPhone needs *Maximize Compatibility*.

### 6.5 Placeholder names

`Owner` / `Owner 2` are invented. Ask the user for their real name and roll
numbers.

### 6.7 LED timing + unlock window redone (was a real security flaw)

The first LED implementation drove green from **door state**, so it stayed lit
for the whole `UNLOCK_MS` (5 s), and `unlockDoor()` re-armed `doorOpenedAt` on
every grant. Two consequences, both bad:

1. The lamp told people the door was open for 5 s, so they queued into it.
2. Because the timer re-armed, a card tapped every few seconds kept the door
   open **forever** — a propped door.

It also corrupted the proxy heuristic: `PROXY_DISTINCT` (3) inside
`PROXY_WINDOW_MS` (5 s) matches exactly the behaviour the lamp encouraged, so
three honest students walking through an open door came out as
`"suspect":true`. Normal queueing was indistinguishable from card stuffing.

**Fixed:**

| Change | Before | After |
|---|---|---|
| Green LED | lit while door open | `LED_GRANT_MS` = **500 ms** pulse per accepted scan |
| Unlock timer | re-armed by every grant | set once on the **first** grant only |
| `PROXY_WINDOW_MS` | 5000 | **2000** — a real queue is a person every 2–3 s and no longer trips it |

Verified on hardware with timestamped taps: unlock at t=2.1 s, second card at
t=6.0 s (inside the window), `door: LOCKED` at t=7.0 s — i.e. 5 s after the
*first* grant, not extended to t=11 s. Second grant printed no `door: UNLOCKED`.

If a demo ever needs a visible "door is open" cue, add an **amber** LED on a
third pin driven by `doorOpen`; do not put green back on door state.

### 6.10 Servo now nudges instead of holding the door open

Asked for by the user: while the door stood open for `UNLOCK_MS` (5 s), reads
and the timing the proxy heuristic depends on felt unreliable. Their instruction
was to "just make it vibrate".

The premise was partly wrong — reads *do* work during the open window (proved by
a `DENIED` logged at T+83 s inside a window opened at T+80 s). What was failing
was reads during the **swing**, which §6.9's polling pause fixed. But the user
chose nudge mode anyway, so it is now the default behaviour.

**What a grant does now:** `startBuzz()` writes `SERVO_UNLOCKED`, waits
`BUZZ_MS` (200 ms), back to locked, `BUZZ_GAP_MS` (150 ms), out again, then
settles — roughly 0.7 s of visible shake. `serviceBuzz()` runs in `loop()`, so
nothing blocks. Log line: `door: nudge (latch tapped, not held)`.

**Verified:** three reads inside two seconds — grant at t=1.1 s, `DENIED` at
t=2.2 s, another grant at t=3.0 s — all processed. No `door: UNLOCKED` appears
any more, and door timing is irrelevant because nothing is held open.

**Trade-off, state it in the report:** the latch never releases, so this is an
*acknowledgement*, not an access-control actuator. **To restore a real swinging
door**, change one line in `handleCard()`:

```c
startBuzz();     // nudge mode (current)
unlockDoor();    // real door: swings open, relocks after UNLOCK_MS
```

Everything else (`UNLOCK_MS`, `serviceDoor()`, the console `unlock` / `lock`
commands) is still there and still works.

### 6.9 Reads dropped while the servo moves — FIXED

The SG90 starting from rest pulls a current step on the 5 V rail. SPI
transactions taken during that burst came back malformed or timed out, so a card
tapped straight after a door movement was silently missed — which is what the
user saw as "the servo messes with the reading times".

**Fix:** `pausePolling(SERVO_SETTLE_MS)` is called from `unlockDoor()` and
`lockDoor()`, and `loop()` skips `PICC_IsNewCardPresent()` while
`pollingPaused()` is true (`SERVO_SETTLE_MS` = 300 ms). Door timing is
unaffected — verified at 5.0–5.1 s across six cycles after the change.

**Side benefit:** the same 300 ms also covers the servo's own settle, so the
first read after a movement cannot land mid-swing.

If a heavier latch ever makes movement longer than 300 ms, raise the constant;
it trades a little responsiveness for reliable reads.

### 6.8 Cosmetic: denial message always claims the door is locked

The denied-card path prints `door: stays LOCKED (card not registered)`
unconditionally, even when the door happens to be open from a previous grant
(the 5 s window). Observed at T+83 s during the real-card test: the denial line
appeared while the door was still open, and `door: LOCKED` followed on schedule.

Behaviour is correct — a denial never unlocks and never extends the window —
only the wording is misleading. Worth making it print the actual state before
the project is written up.

### 6.6 Documentation gaps fixed this session

- `CHEATSHEET.md` §2 used to tell the user to paste a UID into `roster[]` and
  re-upload — contradicts the flash-based `register` command. **Fixed.**
- `README.md` §1 gained an LED wiring table; §2 gained the DIO note earlier.

### 6.11 Timestamps were in the data but nowhere in the UI — FIXED

The user asked "where can I see time stamps?" and the honest answer was
nowhere: `detect.py` built timeline ticks from `x / roll / result / flag` only,
and a session exposed just `date`. The `ts` existed per event in
`events.ndjson` / `/api/summary`, but the dashboard threw it away.

Fixed in two places:

- `analysis/detect.py` (~line 457) — each timeline entry now also carries
  `"ts": stamp(e["t"], e)` and `"src"` (so a clockless board is detectable).
  `stamp()` already refuses to invent a date, so an uptime-only log yields
  `T+3s` rather than a fake 2026 timestamp.
- `analysis/dashboard_template.html` — new **Scan log** panel (every scan, full
  timestamp, card, result, session, newest first, capped at 40), a
  `start–end` window on each timeline row, and `time · roll · result` in the
  tick tooltips. Rows whose events came from `src: uptime` are tagged
  *relative clock*.

Verified live at `http://127.0.0.1:8080/` against the 6 real events in
`server/data/events.ndjson`: panel reads `6 scans, newest first`, newest row
`2026-11-08 11:36:39 · (unregistered) · DENIED`, session row
`2026-11-08 11:33:19–11:36:39`, `/api/summary → 200`, no console errors, no
horizontal page overflow at 420 px or 1100 px. `analysis` tests still 14/14.

### 6.12 Live updates were missing, and the UI was rebuilt

Reported by the user: **“I have to refresh after I scan, else it’s not reflecting
there.”** That was not a network problem. `dashboard_template.html` made exactly one
`fetch("/api/summary")` call during boot and never polled again, so a new scan could
only appear on a manual reload.

Fixed and rebuilt:

- **Polling.** `poll()` now runs on a self-scheduling `setTimeout` every 2 s, is
  skipped while the tab is hidden, and re-fires immediately on `visibilitychange`.
  It compares a signature (`scans | sessions | students | incidents | percentages`)
  and re-renders only when something changed, so hover/focus is not disturbed.
  Failures back off 2 s → 20 s, and the ticker distinguishes *live*, *paused*,
  *receiver stopped answering* and *no receiver here — showing the saved copy*.
- **New scans are announced.** Rows land with a short highlight and a `+N new`
  counter next to the filters.
- **Aesthetic.** Replaced the dark glassy card look with a paper/ink logbook: warm
  sheet, hairline rules, serif display headings, monospace tabular numbers, one
  vermilion accent. A Night theme is included and remembered in `localStorage`.
- **Interaction.** Student search + sort, click any student row for a drawer
  (day-by-day presence, their scans, the arithmetic), incident filters by band,
  scan-log filters, hover tooltips on timeline marks, keyboard `?` `/` `t` `Esc`,
  and a print stylesheet for hand-in.
- **The explainer the user asked for.** A full-screen *How this works* page inside
  the same file: seven sections, plain English, one worked example whose arithmetic
  matches the real scoring code (0.712 → 71 HIGH), and a section on what Wi-Fi
  actually does.

Verified in the browser: with the page open and untouched, a `POST /api/scan` moved
it from 7 to 8 rows within one poll, showing `+1 new` — no reload. Static-copy mode,
the drawer, both themes, the guide overlay, and the 420 px layout all checked; no
console errors. The sample payload still reads 16 students / 8 sessions / 82% /
5 incidents, and `--eval` still prints 4/4 and 0/4.

Note for whoever picks this up: `analysis/state/model.json` is **learned state**.
Every `detect.py` run without `--no-learn` adds the sessions it scored to it, so
repeated runs inflate the baseline and change scores. Delete the file and run once
to return to the documented numbers (63 / 71 / 80 / 71, 82%, 5 incidents).

### 6.13 End-to-end proxy run, 2026-11-09 15:31

Requested by the user: register CS-06, then check a stacked-tap run reaches the
dashboard as a flagged run **without refreshing**.

How it was driven: five different roster cards were sent through the firmware's own
`sim <uid>` path at ~0.2 s spacing (1.20 s for all five). `sim` runs the real decode,
roster, attendance and upload path — it only replaces the physical reader — and it
sets `"simulated":true`, which a hand-tapped card does not.

| Layer | Result |
|---|---|
| Board | taps 3–5 printed `<<< PROXY SUSPECT`, `"suspect":true`, `!! 3 different cards tapped within 2s` |
| Queue | `upload: attempted` → `queue: 0 pending` |
| Receiver | `session_02`, **1 incident, REVIEW 58/100** |
| Why | `impossible-gap 75% of pairs under 0.5s` · `burst 5 cards in 1.0s` · `crowd-anomaly z-score 0.44` |
| Dashboard | open page moved itself from 1 session / 7 scans to **2 sessions / 12 scans / 1 flagged run**, `navigation` entries still 1 — no reload |

Honest caveat: those five records are `simulated:true` and now sit in
`server/data/events.ndjson` as `session_02`. Delete those lines if the audit trail
must contain only hand-tapped scans; the dashboard returns to one session as soon as
they are gone.

What `sim` cannot prove: the physical reader still has to be demonstrated with real
cards (already done separately — see §5), and a *hand-speed* proxy run needs a person
fanning real cards. Machine spacing is what makes the score reproducible here.

### 6.14 Sample-data button — demos with only two cards

The user only has **two physical cards**, so the dashboard gained a **Sample data** control
(`s` on the keyboard). It renders the payload already embedded in the page — the synthetic
16-student / 8-session set — and switches the page into an explicitly labelled sample mode:

- vermilion banner: *synthetic test dataset, 8 sessions, 16 students, 122 scans, 5 flagged runs,
  no card was read to produce any row*;
- ticker `sample data · all 8 sessions · not live`, LED solid instead of pulsing;
- **polling suspended**, so a 2 s poll cannot overwrite the sample with live rows;
- **Back to live** (or the Live button, or `Esc`) clears the banner, resets the change signature
  and resumes polling immediately;
- **session stepping** (see below): the button opens on session 1 of 8, every further press
  advances one session, and `Prev` / `Next` / `All sessions` sit in the banner (`←` / `→` also work).

Verified by clicking it in the running page: gauges went to **8 / 16 / 82% / 5 / 4 / 3**,
incidents **5** (top **HIGH 80/100**), **122** scan rows — still there 3.2 s later, so nothing
overwrote it — and **Back to live** returned to 2 sessions / 2 students / 0 incidents within
one poll. The dataset is whatever was embedded when `dashboard/report.html` was generated, so it
is exactly `analysis/data/*.ndjson` scored by `detect.py`, not a second copy of the numbers.

### 6.15 Walking the eight sessions

The examiner walkthrough needs one session at a time, not the whole dataset at once, so the
Sample-data control is a stepper. State is `VIEW.demoIndex` (`null` = all sessions, `0`–`7` = one
session); `demoPayload(i)` filters the embedded payload down to that session and recomputes what
the page renders:

- `sessions`: just that one, so the timeline and scan log show its scans only;
- `incidents`: only runs whose `session` matches that name, so the incident band is that session's
  evidence and nothing else;
- `students`: all 16 roster rows with `present` 0/1, `total` 1, `percent` 0/100 and `flags` = how
  many of that session's flagged runs the student appears in.

The renderers read `payload.__session` and switch presentation:

- gauges become **Session i/8 · Present n of 16 · Scans · Flagged runs · Review or above · High**;
- the students table header becomes **Arrived**, the bar and pips become the arrival clock time
  taken from the first timeline entry for that roll, and the status pill becomes **present /
  absent** — a term percentage and "below 75%" would be meaningless in a one-session window;
- a roster row with no scan in that session reads *no scan this session* instead of a fake 0%;
- the masthead gains `session i of 8`, the banner names the session with its date, scan and flag
  counts, and the ticker reads `sample data · session i/8 · not live`.

Per-session numbers as embedded. They add up to the whole set: 14+15+17+13+17+18+12+16 = **122
scans** and 1+0+1+0+1+1+0+1 = **5 flagged runs**.

| Session | Scans | Present | Flagged | Review+ | HIGH |
|---|---|---|---|---|---|
| session_01 | 14 | 14 | 1 | 0 | 0 |
| session_02 | 15 | 15 | 0 | 0 | 0 |
| session_03 | 17 | 13 | 1 | 1 | 0 |
| session_04 | 13 | 13 | 0 | 0 | 0 |
| session_05 | 17 | 12 | 1 | 1 | 1 |
| session_06 | 18 | 13 | 1 | 1 | 1 |
| session_07 | 12 | 12 | 0 | 0 | 0 |
| session_08 | 16 | 12 | 1 | 1 | 1 |

Controls: **Sample data** opens on session 1 and every further press advances (wrapping 8 → 1);
`Prev` / `Next` in the banner and `←` / `→` on the keyboard do the same; `All sessions` returns to
the full dataset; `Back to live` (or `Esc`) leaves sample mode and resumes polling.

Verified in the running page: 1/8 → 14 rows / 14 present / 1 flagged, `s` → 2/8 → 15 rows / 0
flagged, `→` → 3/8 → 17 rows / 1 flagged / 1 review, `←` → 2/8, `All sessions` → 8 / 16 / 82% /
5 / 4 / 3 with 122 rows, `Esc` → 2 sessions / 9 rows / live ticker. At 420 px the banner is
388 px wide, its controls wrap inside the border and `scrollWidth` stays 420 (no side scroll).

---

## 7. Do-not list

1. **Don't `erase_flash` casually** — it wipes the 6 registered cards and the
   pending attendance queue. Use the app-only flash at `0x10000`.
2. **Don't flash in QIO** — boot loop (§3.2).
3. **Don't put 5 V on the RC522** — it's a 3.3 V part and will die.
4. **Don't `pkill -f`** — use the `lsof` PID.
5. **Don't `pip install` system-wide** — use `/tmp/espvenv` or a project venv.
6. **Don't trust the IDE's Upload/Serial Monitor** — both are broken here (§3.1).

---

## 8. Document map

| File | Purpose |
|---|---|
| `HANDOFF.md` | this file — state, environment, next steps |
| `PRESENTATION.md` | the presenter runbook: context script, live demo, eight-session walkthrough, Q&A |
| `PROXY_TEST.md` | the 2026-11-09 stacked-tap test: every layer, the arithmetic, the caveats |
| `README.md` | wiring, setup, commands, tuning, proxy limits |
| `CHEATSHEET.md` | one-page bench sheet for the demo |
| `REPORT.md` | the academic report |
| `rfid-attendance-door.ino` | the firmware (door + attendance + LEDs + queue) |
| `rc522_test/rc522_test.ino` | reader-only wiring test |
| `led_test/led_test.ino` | LED pin sweep (currently flashed) |
| `scripts/flash.sh` | one command: wait for the board, compile, flash all four images at 0x10000, read the banner |
| `scripts/` | host-side serial + flashing helpers (see `scripts/README.md`) |
| `analysis/` | risk-scoring engine, synthetic sessions, 14 tests |
| `start.sh` | one command: receiver + `/health` wait + dashboard; `--status` / `--stop` / `--restart` / `--foreground` |
| `server/server.py` | laptop receiver + live dashboard |
| `dashboard/report.html` | generated dashboard (scan log with per-scan timestamps) |
| `wokwi/` | hardware-free simulation |

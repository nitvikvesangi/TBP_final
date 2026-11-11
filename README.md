# RFID-Based Smart Attendance Management + Door Access Control

ESP32 + MFRC522 + SG90 servo. **One scan produces two results:** the door
unlocks for a registered card, and an attendance record is written.

```
scan card -> read UID -> registered? --no--> DENIED log, door stays locked
                              |
                             yes
                              |
                +-------------+-------------+
                |                           |
         servo nudges                   attendance event
         (no hold open)                 (once per session, timestamped)
                                              |
                                    flash queue -> optional POST
```

Everything works with **no internet at all**. Wi-Fi is only for timestamps and
uploading records.

---

## 0. Quick start — one command

```bash
./start.sh
```

That starts the receiver, waits until it answers `/health`, and opens the live
dashboard. The token and the port are read from `secrets.h` (`CLOUD_TOKEN`, and the
port out of `CLOUD_URL`), so the laptop and the flashed sketch cannot drift apart:

```
  starting   : python3 server/server.py --port 8080
  pid        : 26597   log: server/receiver.log
  token      : set (from secrets.h)
  dashboard  : http://127.0.0.1:8080/  (opening)
  on the LAN : http://192.168.1.4:8080/
```

| Command | What it does |
|---|---|
| `./start.sh` | start (or reuse) the receiver, open the dashboard |
| `./start.sh --status` | running? which pid? how many records, and the last one |
| `./start.sh --stop` | stop the receiver this script started |
| `./start.sh --restart` | stop, then start |
| `./start.sh --foreground` | stay in this terminal, Ctrl-C to stop (no PID file) |
| `NO_OPEN=1 ./start.sh` | start without opening a browser |
| `./start.sh --port 9000` | another port — keep `CLOUD_URL` in step with it |

It reuses a receiver you already started by hand on that port instead of failing,
and prints the LAN address the board must be able to reach. If the laptop's IP has
changed since you uploaded the sketch, it says so, because that is the one thing
that silently stops the dashboard while the door keeps working.

### What works with only the board powered

| Board alone — USB or any 5 V supply | Needs the laptop running `./start.sh` |
|---|---|
| read a card, open the door, green/red LED | the live dashboard in a browser |
| attendance marked in flash, `list` / `report` over serial | `GET /api/summary` |
| scans queued to POST later, replayed when Wi-Fi is back | `server/data/events.ndjson` (your audit trail) |
| honest timestamps (`ntp`, or `T+42s` uptime) | `dashboard/report.html` refreshed live |

The board never needs the laptop to grant or deny a card — that decision is local
and stays that way. Pull the laptop away mid-demo and the door still works; the
records wait on the board and upload by themselves once the server is reachable.

**Two failures worth knowing:** `port 8080 is already used by pid …` means
something else owns the port — `./start.sh --status` names it, or use `--port`. A
`401` on uploads means the sketch's `CLOUD_TOKEN` and `secrets.h` disagree, so fix
`secrets.h`, run `./start.sh`, and reflash with `./scripts/flash.sh`.

**Flashing is not the IDE's Upload button.** On this Mac both the IDE upload and plain `arduino-cli upload` die with `termios.error: (22, 'Invalid argument')` (see `scripts/README.md`). `./scripts/flash.sh` is the working path: it waits for the board, compiles into a clean directory, writes bootloader + partition table + boot_app0 + app, and prints the boot banner so you can see `System Ready`. It needs a **data** USB cable - a charge-only cable gives you no `/dev/cu.usbserial-*` at all, and nothing can be flashed or read.

---

## 1. Wiring

### MFRC522 (must be 3.3 V — 5 V destroys the module)

| MFRC522 | ESP32 |
|---|---|
| SDA (SS) | GPIO 5 |
| SCK | GPIO 18 |
| MOSI | GPIO 23 |
| MISO | GPIO 19 |
| RST | GPIO 22 |
| 3.3V | 3V3 |
| GND | GND |
| IRQ | not connected |

Cheap modules often report firmware version **`0x82`** instead of `0x92`. That
is a clone of the MFRC522, not a fault — it reads cards correctly and the
firmware accepts it. Only `0x00` / `0xFF` means the SPI wiring is wrong.

### Servo

| Servo | ESP32 |
|---|---|
| Signal (orange) | GPIO 13 |
| V+ (red) | 5V (external 5 V supply preferred — common GND with ESP32) |
| GND (brown) | GND |

If the ESP32 resets or the serial port disconnects when the servo moves, the
servo is drawing too much current from the board's regulator. Use a separate
5 V supply and tie the grounds together, and fit a **470 µF** electrolytic
across the 5 V rail (long leg to +) close to the servo wires.

### Indicator LEDs

| LED | ESP32 | Wiring |
|---|---|---|
| Green — granted / door open | GPIO 26 | pin → 220–330 Ω → long leg, short leg → GND |
| Red — denied | GPIO 27 | pin → 220–330 Ω → long leg, short leg → GND |

Green pulses for **0.5 s** on every accepted scan (`LED_GRANT_MS`); red holds
**0.5 s** on a refusal (`LED_DENY_MS`). Neither is blocking — `serviceLeds()`
clears both from `loop()`.

**Why green is a pulse and not a door-open lamp.** Driving it from door state
kept it lit for the whole 5 s unlock, which advertises *walk straight through*:
people queue into the open window, three different cards land inside the proxy
window, and the whole burst gets flagged as proxy attendance. Worse, the grant
path re-armed `doorOpenedAt` on **every** tap, so a card tapped every few seconds
held the door open indefinitely. The unlock window is now fixed from the
**first** grant and further taps inside it change nothing.

**The resistor is not optional**, and the value matters. 3.3 V straight into a
bare LED overdrives it and stresses the pin, while anything above about 1 kΩ
passes too little current to see. 220 Ω gives ~6 mA and 330 Ω about 4 mA — both
clearly visible. Wires of any colour are fine; what matters is
`GPIO → resistor → long leg → short leg → GND`.

**Check the ground rail before blaming the resistor.** On almost every
breadboard the power rails are **split at the halfway mark**, so the left and
right halves are two separate rails. If the ESP32's GND sits on one half and the
LEDs on the other, both LED legs end up near 3.3 V and nothing lights — even
though the GPIO is provably driving high. This is the single most common reason
an indicator LED "doesn't work".

The one-second test: meter on **DCV 20**, black probe on the ESP32 GND pin, red
probe on the LED's **short leg**. It must read **0 V**. Reading 3.3 V means the
ground path is open. Bridging the rail with a short jumper fixes it.

---

## 2. Libraries (Arduino IDE → Library Manager)

- `MFRC522` — Miguel Balboa
- `ESP32Servo` — Kevin Harrington

Board: **ESP32 Dev Module**. Partition scheme: default (LittleFS area is used
for the offline queue). **Flash mode: DIO** — the Dev Module profile defaults to
QIO, but many cheap boards ship a flash chip without QIO support, which causes a
boot loop (`qio_mode: Failed to set QIE bit` -> `assert failed:
__esp_system_init_fn_init_flash`). Choose `Tools > Flash Mode > DIO`, or pass
`--board-options FlashMode=dio` on the command line.

Baud rate: **115200**.

---

## 3. Registering your cards (no re-flashing)

1. Open the Serial Monitor.
2. Scan an unregistered card. You get:

```
         door: stays LOCKED (card not registered)
         UID = 4A 1F 9C 2E
         ^ register it:  register <uid> <roll> <name>
[DENIED] ...
```

3. Type the command with that UID:

```
register 4A 1F 9C 2E CS-05 Priya Nair
registered 4A 1F 9C 2E -> Priya Nair (CS-05)
```

4. Scan it again — it opens the door. The card is saved in flash
   (`/roster.txt`), so it survives a reboot and never needs a re-upload.

| Task | Command |
|---|---|
| add a card | `register <uid> <roll> <name>` |
| delete a card | `remove <uid>` |
| see everything | `list` |

The four demo cards are seeded once, on the very first boot only. You only have
1–2 real cards — that is enough; use `sim` for the rest of the class.

### Updating the firmware without losing your cards

The roster lives in LittleFS (`/roster.txt`), not in the sketch, so a normal
upload keeps it. Only an erase (`erase_flash`, or writing a merged image at
`0x0`) destroys it — after that the board re-seeds the four demo cards. To
update safely, write the application alone at `0x10000`; `HANDOFF.md` §4 has the
exact command.

---

## 4. Serial commands

| Command | What it does |
|---|---|
| `help` | list commands |
| `sim AA BB CC DD` | **fake card scan** — same code path as real hardware, without the card |
| `list` | roster + who is marked present |
| `session` | start a new session (clears PRESENT flags) |
| `register <uid> <roll> [name]` | save a card to flash — **no re-upload needed** |
| `remove <uid>` | delete a card from flash |
| `queue` | how many records are still un-uploaded |
| `dump` | re-print every queued record as JSON, between BEGIN/END markers |
| `upload` | force a queue upload now |
| `reboot` | restart the ESP32 |
| `unlock` / `lock` | test the servo alone |
| `wifi` | Wi-Fi, IP, time-source status |

`sim` is what lets you demo a whole class of students with two physical cards.
To demo a *fake/unregistered* ID, run `sim DE AD BE EF` — that UID is not in
the roster, so it is refused exactly like an unknown card.

---

## 5. Does the ESP32 need a connection all the time?

**No.** The firmware is offline-first:

| Situation | Behaviour |
|---|---|
| No Wi-Fi configured | pure local operation, records stay in flash |
| Hotspot on at boot | connects, syncs NTP, uploads queued records |
| Hotspot off / phone asleep | scans keep working, records queue in flash |
| Hotspot comes back | retries upload every 20 s, backlog goes up in order |

So a phone hotspot is perfectly fine — treat it as *"the network happens to be
there"*, not as a dependency of the door or the attendance.

Two practical gotchas:

- **2.4 GHz only.** ESP32 cannot see a 5 GHz hotspot. On iPhone enable
  *Settings → Personal Hotspot → Maximize Compatibility*. Most Android
  hotspots are 2.4 GHz already.
- **Campus Wi-Fi with a login page will not work** (captive portal / WPA2-
  Enterprise). That is a good argument for the hotspot in your report.

**Recommended for the demo:** turn the hotspot on *before* powering the ESP32,
so it boots, syncs NTP, and every record gets a real timestamp.

### Timestamps without internet

The ESP32 has no battery-backed clock. So:

- Wi-Fi up → NTP gives real local time (`"src":"ntp"`), e.g. `2026-11-07T10:15:00`
- No Wi-Fi → the record gets `"src":"uptime"` and `"ts":"T+42s"` (seconds since
  power-on)

The sketch does **not** fake a date when it has no clock — an honestly-labelled
relative time is defensible in a viva; a wrong absolute date is not. If you want
real timestamps with no internet at all, add a DS3231 RTC module (~₹100).

---

## 6. Cloud upload (optional)

Fill in at the top of the sketch:

```cpp
const char* WIFI_SSID   = "MyHotspot";
const char* WIFI_PASS   = "password";
const char* CLOUD_URL   = "http://192.168.43.5:8080/api/scan";
const char* CLOUD_TOKEN = "S3cret";   // same value as server --token
```

Each record is POSTed as JSON:

```json
{"uid":"01 02 03 04","name":"Alice Sharma","roll":"CS-01","result":"GRANTED",
 "attendance":"PRESENT","suspect":false,"simulated":false,
 "ts":"2026-11-07T10:15:00","src":"ntp"}
```

`CLOUD_URL` empty ⇒ offline mode, nothing is sent, everything is kept locally.

### The receiver in this repo

`server/server.py` is a zero-dependency receiver that also serves the live
dashboard. Start it **on the laptop sharing the hotspot**:

```bash
python3 server/server.py --token S3cret
```

```
RFID attendance receiver
  upload URL : http://172.20.10.3:8080/api/scan
  dashboard  : http://172.20.10.3:8080/
  events file: server/data/events.ndjson
```

Paste the printed **upload URL** into `CLOUD_URL`, the token into
`CLOUD_TOKEN`, upload once, and every scan from then on lands in the dashboard.

| Route | Purpose |
|---|---|
| `POST /api/scan` | one event → appended to `data/events.ndjson` |
| `GET /api/summary` | attendance % + scored incidents (reuses `detect.py`) |
| `GET /` | dashboard, live |
| `GET /health` | `{"ok":true}` |

**Security:** with `--token`, any POST without a matching `X-Device-Token`
header gets **401**. Wrong JSON or missing fields get **400**. That is device
authentication, not just a check that something arrived.

### The standalone dashboard file

The same UI also ships as a single self-contained HTML file, `dashboard/report.html`,
for handing in or opening with no server at all. Its markup, styles and JS live in
**`analysis/dashboard_template.html`** — that file is the source of truth, and
`detect.py --dashboard` fills its `__DATA_JSON__` placeholder:

```bash
cd analysis && python3 detect.py --dashboard ../dashboard/report.html data/*.ndjson
```

To rebuild the shipped file from an existing payload without re-running detection:

```bash
python3 -c "import json,pathlib;t=pathlib.Path('analysis/dashboard_template.html').read_text();p=pathlib.Path('dashboard/report.json').read_text();pathlib.Path('dashboard/report.html').write_text(t.replace('__DATA_JSON__',p))"
```

Opened straight from disk it requests `/api/summary`, gets a 404, and says so in one
line — “no receiver here — showing the saved copy” — then backs off to a slow retry
instead of hammering the file server. The page is only *live* when `server/server.py`
is serving it.

### What the dashboard does while you watch it

It is not a screenshot: it polls `/api/summary` every 2 seconds, and only re-renders
when the numbers actually changed.

| Control | What it does |
|---|---|
| **Live / Paused** | toggle polling; the dot is green when live, grey when paused, vermilion while a receiver is unreachable |
| **Paper / Night** | two flat themes, remembered in `localStorage` (`t` on the keyboard flips it) |
| **Find** + **Roll / Attendance / Flags** | filter and sort the roster (`/` focuses the box) |
| **click a student row** | side drawer: day-by-day presence, their scans, and the exact arithmetic behind their % |
| **All / Review+ / High only** | filter flagged runs by band |
| **show the calculation** | per-signal value × weight = points, then the raw total and the final score |
| **hover a timeline mark** | exact time, card and result for that scan |
| **Everything / Granted / Denied / Flagged** | filter the scan log; new rows flash and a `+N new` counter appears |
| **How this works** (`?`) | the full plain-English explainer, including one worked example |
| **Sample data** (`s`) | opens the embedded synthetic dataset one session at a time (16 students, 8 sessions, 122 scans, 5 flagged runs) with a banner saying it is synthetic; `Next` / `Prev` step through the sessions, `All sessions` shows the whole set, **Back to live** returns |
| **Print** | paper-friendly stylesheet for the report appendix |

New scans land within about two seconds of arriving at the receiver, with no reload.

### Where the timestamps are

Every scan carries the time the **board** recorded it (`ts`), and the dashboard
now shows that time in three places, all from the same field:

| Place | What you see |
|---|---|
| **Scan log** panel (bottom) | one row per scan: full `2026-11-08 11:33:19` time, card, GRANTED/DENIED, session — newest first, capped at 40 |
| **Session timeline** rows | the session's start–end window, e.g. `11:33:19–11:36:39` |
| **Timeline ticks** | hover any tick for `time · roll · result` |

Times are device time (IST once NTP has synced). If the board booted with no
clock, the value is honestly labelled `T+3s` and the row is marked
*relative clock* instead of inventing a date. The same `ts` is in the raw
`events.ndjson` and in `/api/summary`, so nothing here is dashboard-only.

### The “How this works” page

The **How this works** button (or `?`) opens a seven-part explanation written for
someone who has never seen an RFID reader: one tap end to end, why attendance is
counted per day, what a real queue looks like versus a stack of cards, the full
weighted-score table with one worked example that adds up to **71 / 100 HIGH**, the
four bands, what Wi-Fi actually does, and what the system honestly cannot do. It is
inside the same HTML file — nothing to install, nothing to load.

### Reading list, in order

| File | Read it for |
|---|---|
| `PRESENTATION.md` | the spoken runbook: context script, live demo, the eight-session walkthrough, likely questions |
| `PROXY_TEST.md` | one real stacked-tap run, layer by layer, with the actual arithmetic and the caveats |
| `HANDOFF.md` | build state, landmines on this Mac, verified evidence, open issues |
| `CHEATSHEET.md` | the one-page bench sheet for the demo |
| `REPORT.md` | the write-up for submission |

---

## 7. Proxy attendance: what this system can and cannot detect

Plain RFID UID checking **cannot prove who is holding the card**. That is the
honest limitation in your report, and the sketch is built around it rather than
pretending otherwise. What it does implement:

| # | Check | Rule | Logged as |
|---|---|---|---|
| 1 | Unknown card | UID not in roster | `result: DENIED` — door stays locked |
| 2 | Card left on reader | same UID re-read within 3 s | ignored, no duplicate record |
| 3 | Repeat scan | same student already present this session | `attendance: ALREADY_MARKED` — door still opens, attendance counted once |
| 4 | **Bulk scan (proxy)** | ≥ 3 *different* cards tapped within 2 s | `suspect: true` — flagged for review, still granted |

Check 4 is the realistic proxy attack in a college setting: one student walks
up with five friends' cards and taps them one after another. A genuine queue of
students arrives seconds apart; a stack of cards is tapped in under a second.
That timing difference is what `PROXY_DISTINCT` / `PROXY_WINDOW_MS` catches.

Deliberately **not** denied — only flagged. Rapid legit entry is rare but
possible, and silently locking out a registered student during a demo is worse
than a flagged record.

What it cannot do: a cloned card holds the same UID as the original, so the
system logs the *owner* as present. Card cloning is invisible at UID level —
state that in the report as a limitation, and note strong authentication
(MIFARE DESFire, challenge-response, second factor) as future scope.

---

## 8. Demo script (5 minutes)

| Step | Action | Expected serial output |
|---|---|---|
| 1 | Power up, hotspot on | `rc522: ok (version 0x92)` — `0x82` on clone modules is fine — `ntp: ok`, `System Ready` |
| 2 | `sim 01 02 03 04` (or scan Alice's card) | `door: nudge`, **green blips 0.5 s**, `GRANTED / PRESENT` |
| 3 | Wait 5 s | door LOCKED |
| 4 | `sim DE AD BE EF` (unregistered) | `DENIED / NOT_RECORDED`, door stays LOCKED, **red LED flashes** |
| 5 | `sim 01 02 03 04` again | `GRANTED / ALREADY_MARKED` — no double count |
| 6 | `sim 11 22 33 44`, `sim 55 66 77 88`, `sim AA BB CC DD` quickly | last records show `<<< PROXY SUSPECT` |
| 7 | `list` | 4 of 4 present |
| 8 | `queue` | 0 pending (Wi-Fi up) or N pending (offline) |

Sample output:

```
[2026-11-07T10:15:00] Alice Sharma   CS-01 GRANTED  PRESENT
         door: UNLOCKED
{"uid":"01 02 03 04","name":"Alice Sharma",...}
         door: LOCKED
[2026-11-07T10:15:21] -              -     DENIED   NOT_RECORDED
         door: stays LOCKED (card not registered)
```

---

## 9. Demo without hardware

`wokwi/diagram.json` + `wokwi/libraries.txt` are set up for
[wokwi.com](https://wokwi.com). Wokwi's MFRC522 is officially supported and
ships six preset cards — Blue, Green, Yellow, Red, NFC tag, Key fob — so you can
show 4 registered students and 2 unregistered cards with no extra tags. The
roster in the sketch already uses those preset UIDs.

Wokwi instructions are in `wokwi/README.md`.

---

## 10. Tuning

| Constant | Default | Meaning |
|---|---|---|
| `UNLOCK_MS` | 5000 | only used by the manual `unlock` command now — a normal grant **nudges** the servo instead of holding the latch open |
| `BUZZ_MS` / `BUZZ_GAP_MS` | 200 / 150 | length of each nudge pulse and the gap between the two |
| `RE_READ_MS` | 3000 | ignore the same card lingering on the reader |
| `SESSION_MS` | 3600000 | attendance window (1 hour) |
| `PROXY_WINDOW_MS` | 2000 | bulk-scan detection window — short enough that a normal queue (a person every 2–3 s) cannot trip it |
| `PROXY_DISTINCT` | 3 | distinct cards in that window to flag |
| `SERVO_LOCKED` / `SERVO_UNLOCKED` | 0 / 90 | tune to your latch |
| `SERVO_SETTLE_MS` | 300 | card polling is suspended this long after each servo move — the motor's current step was corrupting SPI reads, so taps right after a movement were dropped |
| `LED_GRANT_MS` / `LED_DENY_MS` | 500 / 500 | green confirmation pulse / red refusal flash — matched to the same length |

---

## 11. Beyond the fixed threshold: the risk model

The `suspect` flag in the firmware is deliberately simple (three cards in five
seconds). The real detector lives in `analysis/` — a weighted, learning model
that reads the same NDJSON log and scores each suspicious run 0-100 from seven
signals, with an explicit discount for students who habitually arrive together.

```bash
cd analysis
python3 simulate.py --sessions 8                      # labelled test data
python3 detect.py --eval --state /tmp/st.json          # measured precision/recall
python3 detect.py --state state/model.json --min-band REVIEW
```

See `analysis/README.md` for the signal table, the measured results and the
honest limitations. The firmware stays untouched: the board keeps working
without a laptop, and the model runs when you have a machine to run it on.

---

## 12. Do we need a public dataset?

**No — and no suitable one exists.** There is no Kaggle dataset of RFID
card-tap timing at a doorway; attendance datasets online are spreadsheet-style
(name, date, present) with no sub-second timing, which is precisely the field
this model needs. The closest public artefacts are:

| Source | What it is | Usable here? |
|---|---|---|
| Kaggle *Employee Attendance Fraud & Anomaly Detection* | 200 employees, ~101k QR-code scans with GPS/device/schedule fields and fraud labels | Only for a different experiment (arrival-time behaviour), not for tap timing |
| Zenodo *AI-Driven Behavioral Anomaly Detection for RFID-Based Attendance* | Seven-feature behavioural model for buddy punching | Related work to cite in the report |
| Zenodo *BioTag RFID Dataset* (Rutgers) | RSSI/phase signatures of 41 people | Future scope: physical-layer identity, the real answer to cloning |

Your own corridor is the right baseline: the 0.5 s doorway limit depends on
*human walking speed through one door*, which is why a log from someone else's
building would not transfer anyway. Five or ten sessions from your own setup
are worth more than a hundred thousand rows from elsewhere.

> **Compile status:** this sketch is compile-verified with arduino-cli and ESP32
> core 3.3.12 — `1107359 bytes (84%) flash` (1 107 147 before the indicator LEDs
> were added), `52244 bytes (15%) RAM`, zero warnings. A project-local toolchain sits in `.tools/` (~7 GB, nothing installed
> system-wide). Command-line build:
>
> ```bash
> cd rfid-attendance-door
> ./.tools/arduino-cli --config-file .tools/cli.yaml compile --fqbn esp32:esp32:esp32 .
> ```
>
> If you add much more code and hit a flash limit, switch the partition scheme to
> **Huge APP (3 MB No OTA)**. Delete the toolchain with `rm -rf rfid-attendance-door/.tools`
> when you are done.

### Capturing real sessions

Every scan is already printed as one JSON line on the serial port, and `dump`
re-prints whatever is queued in flash. To get a file:

```bash
# macOS: adjust the device name from `ls /dev/cu.*`
stty -f /dev/cu.usbserial-0001 115200
cat /dev/cu.usbserial-0001 > analysis/data/session_real_01.ndjson   # Ctrl-C to stop
```

Or copy the Serial Monitor text into a `.ndjson` file. Then
`python3 detect.py analysis/data/session_real_01.ndjson --state analysis/state/model.json`.

With only two cards you cannot produce a realistic multi-student session from
hardware, so state plainly in the report that the multi-student evaluation uses
the labelled synthetic generator (`analysis/simulate.py`), while the hardware
run demonstrates the end-to-end path. That is an honest split and an examiner
can check both.


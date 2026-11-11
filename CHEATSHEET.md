# DEMO CHEAT SHEET — one page

**RFID Attendance + Door Access** · baud **115200** · board **ESP32 Dev Module**

> Walking someone through it? The spoken runbook is `PRESENTATION.md`. This page is the bench reference.

---

## 0 · Before you plug in

- [ ] RC522 on **3.3 V** (never 5 V), all 7 wires seated
- [ ] Servo signal → **GPIO 13**, servo GND **shared** with ESP32 GND
- [ ] Green LED → **GPIO 26**, red LED → **GPIO 27**, each via **220–330 Ω**
- [ ] Hotspot ON *before* power-up (for real timestamps)
- [ ] Arduino IDE Serial Monitor open at **115200**
- [ ] Dashboard up: `./start.sh` (or `./start.sh --status` to see if it already is)

---

## 1 · Power-up — you must see these lines

```
=== RFID Attendance + Door Access ===
rc522: ok (version 0x92)          <- 0x82 on clone modules is also fine
flash: ok
wifi: connected, ip 172.20.10.x     <- or: wifi: disabled (offline-only mode)
ntp: ok
roster: 4 cards
System Ready - scan a card, or type 'help'
```

**If `rc522: NOT detected`** → 3.3 V / GND / SPI wire is loose. Fix before anything else.

---

## 2 · Cards in the demo roster

| Card | UID | Student | Result |
|---|---|---|---|
| Blue | `01 02 03 04` | Alice · CS-01 | GRANTED |
| Green | `11 22 33 44` | Rohit · CS-02 | GRANTED |
| Yellow | `55 66 77 88` | Sara · CS-03 | GRANTED |
| Red | `AA BB CC DD` | Imran · CS-04 | GRANTED |
| **Your card** | `20 74 0B 56` | Owner · CS-05 | GRANTED |
| **Second card** | `2E 63 64 F8` | Owner 2 · CS-06 | **DENIED** — deliberately unregistered |
| NFC tag | `04 11 22 33 44 55 66` | — | **DENIED** |
| Key fob | `C0 FF EE 99` | — | **DENIED** |

Five cards are registered right now (`list` confirms CS-01 … CS-05). `CS-06`
(`2E 63 64 F8`) is **deliberately left out**, so your second card is the reject card:
`DENIED` + red LED, door stays shut. Put it back with
`register 2E 63 64 F8 CS-06 Owner 2`. Any card not in that list behaves the same way.

Your own card is unknown at first → the sketch prints its UID. Type
`register 4A 1F 9C 2E CS-05 Your Name` in the Serial Monitor: it saves to flash,
**no re-upload needed**. Do not edit `roster[]` and re-flash — that array only
seeds demo cards on a first boot.

---

## 3 · Commands (type in Serial Monitor)

| Command | Does |
|---|---|
| `help` | list commands |
| `sim AA BB CC DD` | fake scan, same code path as hardware |
| `register 4A 1F 9C 2E CS-05 Priya` | **save a card to flash, no re-upload** |
| `remove 4A 1F 9C 2E` | delete a card |
| `list` | roster + who is PRESENT |
| `session` | new session, clears PRESENT |
| `queue` | pending un-uploaded records |
| `dump` | re-print every queued record (BEGIN/END markers) |
| `upload` | force upload now |
| `unlock` / `lock` | test servo only |
| `wifi` | IP + time-source status |

---

## 4 · The 6-step demo — say / do / expect

| # | Do | Expect on screen |
|---|---|---|
| 1 | Scan **Blue** | `door: nudge (latch tapped, not held)` then `"result":"GRANTED","attendance":"PRESENT"` |
| 2 | Watch the servo | two quick pulses, then it settles. Green blips 0.5 s per scan, never stays on, and the latch is **not** held open |
| 3 | Scan **NFC tag** | `door: stays LOCKED` + `[DENIED]` + `UID = 04 11 22 33 44 55 66` |
| 4 | Scan **Blue** again | `GRANTED` + `"attendance":"ALREADY_MARKED"` (no double count) |
| 5 | `sim 11 22 33 44` → `sim 55 66 77 88` → `sim AA BB CC DD` fast | `!! 3 different cards tapped within 2s - possible proxy attendance` |
| 6 | `list` | all 4 show `PRESENT`, `-- 4 of 4 present` |
| 7 | `queue` | `queue: 0 pending` with Wi-Fi, or `N pending` offline |

**Line to say:** *"The door answers 'may this card enter'; the record answers 'is this counted'. Two separate decisions."*

---

## 5 · Analysis — exact commands, exact numbers

```bash
cd rfid-attendance-door/analysis

python3 simulate.py --sessions 8
python3 detect.py --eval --state /tmp/st.json
python3 detect.py --state state/model.json --min-band REVIEW
python3 detect.py data/session_05.ndjson --state state/model.json --explain
python3 detect.py --state state/model.json --dashboard ../dashboard/report.html
```

**`--eval` must print:**

```
caught 4/4 attack sessions   false alarms 0/4 clean sessions
precision 1.00   recall 1.00
```

**`--min-band REVIEW` must print these scores:**

| Session | Score | Band |
|---|---|---|
| 03 | 63 | REVIEW |
| 05 | **71** | HIGH |
| 06 | **80** | HIGH (PROBING) |
| 08 | **71** | HIGH |

**Dashboard:** 16 students · 8 sessions · **82% average attendance** · 5 incidents.

**Timestamps — three places, one source:** the **Scan log** panel lists every scan
with its full `2026-11-08 11:33:19` time; each timeline row shows its
`start–end` window; hovering a tick shows `time · roll · result`. A board that
booted without a clock shows `T+3s` and a *relative clock* tag, never a fake date.

**Showing the dashboard to someone:** press **How this works** (or `?`) and it explains the
whole thing in plain English, with one worked example that adds up to 71/100 HIGH.
If they ask what the Wi-Fi is for: the clock and the upload, nothing else — the door
runs with the network off. Other keys: `/` to search, `t` for Night, `Esc` to close.
New scans appear on their own within ~2 s; if the dot is grey the page is paused.

The full write-up of the proxy test — every layer, every number, what to say about it: `PROXY_TEST.md`.

**Only two cards on the bench?** Press **Sample data** (or `s`): the dashboard loads the synthetic
16-student / 8-session dataset — 122 scans, 5 flagged runs, 82% average — and a banner says
plainly that no card produced it. Every panel (students, incidents, timeline, scan log) is the
real renderer, so it looks and behaves exactly like live data.

It opens on **session 1 of 8**. Each **Next** (or `s`, or `→`) advances one session, **Prev** (or
`←`) goes back, and **All sessions** shows the whole set. Inside one session the students table
switches to arrival times with present/absent instead of a term percentage, the gauges read
session / present / scans / flagged, and the incident panel lists only that session's runs --
which is the order to walk an examiner through. **Back to live** (or `Esc`) returns.

**`--explain` arithmetic (single file, cold start, zero terms omitted):**
`0.40x1.00 + 0.20x1.00 + 0.12x0.24 + 0.05x1.00 = 0.679 -> 68/100 REVIEW`

---

## 6 · Numbers to quote (memorise these 4)

- **0.5 s** — two different cards closer than this cannot be two people at one door
- **0.40** — weight of the impossible-gap signal (biggest)
- **63 → 71** — same cheat, first time vs repeating: REVIEW becomes **HIGH**
- **4/4 caught, 0 false alarms** — on 8 synthetic sessions

---

## 7 · If it goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `rc522: NOT detected` | 3.3 V / GND / wiring | reseat, check 3.3 V not 5 V |
| ESP32 resets when servo moves | servo drawing too much | external 5 V + common ground |
| Nothing on serial | wrong baud | 115200 |
| Timestamp shows `T+42s` | no NTP | hotspot on at boot |
| Same card scans twice | card left on reader | normal, ignored for 3 s |
| LED never lights | **split ground rail** (most common), or LED reversed | meter on DCV 20: LED **short leg vs ESP32 GND must read 0 V**. 3.3 V there = no ground. Buzz the two far ends of the blue rail |
| Dashboard blank | opened `report.json` instead of HTML | open `dashboard/report.html` |

---

## 8 · Cloud path (laptop + hotspot)

```bash
cd rfid-attendance-door
python3 server/server.py --token S3cret
```

Prints `upload URL: http://172.20.10.x:8080/api/scan`.

- paste that into `CLOUD_URL`, `S3cret` into `CLOUD_TOKEN`, upload once
- open `http://172.20.10.x:8080/` → dashboard says **live**
- wrong token → **401**, bad JSON → **400** (say this out loud)

**If Wi-Fi never connects:** records still queue. `queue` shows `N pending`,
`upload` forces a retry. Nothing is lost.

---

## 9 · Panel/wifi fallback

Wokwi (no hardware): new ESP32 project → paste `rfid-attendance-door.ino` as `sketch.ino`,
paste `wokwi/diagram.json`, keys `b g y r n k` pick a card, `t` taps it.

**Have ready:** recorded video/screens of the 6-step demo — hardware fails at the worst time.

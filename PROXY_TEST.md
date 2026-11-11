# The proxy test — everything that happened, explained

> **One line:** five different cards were pushed through the board in **1.20 s**. The board
> flagged three of them as proxy suspects, the laptop scored the run **REVIEW 58/100**, and
> the dashboard showed it without anyone touching the page.
>
> This file explains every layer, every number and every word in that sentence — including
> the parts that are simulated, and the parts this test does **not** prove.

---

## 1 · What was being tested

Three separate claims, which fail independently:

| # | Claim | Where it lives | Verdict |
|---|---|---|---|
| 1 | The **board** notices several different cards arriving too fast to be several people | `rfid-attendance-door.ino` | **confirmed** — 3 taps printed `<<< PROXY SUSPECT` |
| 2 | The **laptop** turns that run into a score and a band | `analysis/detect.py` | **confirmed** — `REVIEW 58/100`, arithmetic printed |
| 3 | The **dashboard** shows it while it is open, with no reload | `dashboard/report.html` | **confirmed** — self-updated, `navigation` entries stayed 1 |

It was **not** a test of the physical reader (real cards on the RC522), which had already been
verified separately, and it was **not** a hand-fanned stack of cards — see §12.

---

## 2 · The bench at that moment

| Item | Value |
|---|---|
| Board | ESP32 Dev Module, `192.168.1.11`, RSSI ≈ −45 dBm |
| Reader | MFRC522, clone chip, version register `0x82` |
| Serial | `/dev/cu.usbserial-0001` @ **115200** |
| Firmware | door on **GPIO 13** (nudge mode), green **26**, red **27**, SS **5**, RST **22** |
| Clock | NTP synced (`"src":"ntp"`), device time **IST** |
| Receiver | `python3 server/server.py --port 8080 --token S3cret` on the laptop |
| Dashboard | `http://127.0.0.1:8080/`, open in a browser the whole time |

---

## 3 · Step 1 — putting CS-06 back in the roster

The card `2E 63 64 F8` had been deliberately **unregistered** for a while, so the red LED and
the `DENIED` path could be shown with a real card. Restoring it is a serial command — no
re-flash, no source edit, because the roster lives in LittleFS:

```
> register 2E 63 64 F8 CS-06 Owner 2
registered 2E 63 64 F8 -> Owner 2 (CS-06)

> list
-- roster --------------------------------------------
  01 02 03 04    CS-01 Alice Sharma     -
  11 22 33 44    CS-02 Rohit Verma      -
  55 66 77 88    CS-03 Sara Khan        -
  AA BB CC DD    CS-04 Imran Qureshi    -
  20 74 0B 56    CS-05 Owner            -
  2E 63 64 F8    CS-06 Owner 2          -
-- 0 of 6 present
```

Six cards, and the `-` column is because the roster had just been reset: nobody is `PRESENT`
until they tap again in this session.

**Why this mattered for the test:** the burst needed at least **three distinct registered
cards**. With five on the roster and one deliberately out, there were exactly five usable —
enough for the burst, and one short of a sixth card.

---

## 4 · Step 2 — how a "stacked tap" was driven

A stacked tap is one person holding several cards and fanning them across the reader. The point
of the attack is that **five different people appear to arrive within a second**.

A human hand cannot tap five cards 0.2 s apart, and I am not able to move your cards, so the
burst was sent through the firmware's own test command:

```
> sim 01 02 03 04
-- simulated scan --
```

`sim <uid>` is not a shortcut in the network path — it is a shortcut in **one** place only.
Look at what it shares with a real tap:

| Stage | Real tap | `sim` |
|---|---|---|
| RC522 reads a physical card | ✅ real | ❌ replaced by the typed UID |
| UID is formatted and looked up in the roster | ✅ | ✅ same `handleCard()` |
| Unknown card → red LED, `DENIED`, logged | ✅ | ✅ same branch |
| Attendance (`PRESENT` / `ALREADY_MARKED`) | ✅ | ✅ same counters |
| Proxy window check across recent taps | ✅ | ✅ same `rememberScan()` |
| Green LED + servo nudge | ✅ | ✅ same `grantFlash()` |
| Record written to the queue and uploaded | ✅ | ✅ same `logEvent()` |
| The record is marked `"simulated":true` | ❌ (`false`) | ✅ |

So the only thing `sim` skips is the radio. That is exactly why the records it produces say
`"simulated":true` — the data tells you the truth about its own origin. Everything the two
detection layers look at (which cards, in what order, how far apart) is identical.

One real difference worth knowing: a **physical** tap of the same card within `RE_READ_MS` is
ignored as "card still resting on the reader". `sim` bypasses that dedupe on purpose, so a typed
UID always produces a record.

---

## 5 · Step 3 — the burst, tap by tap

The five commands were written to the serial port back to back, each draining 0.20 s of output.
Total wall time for the loop: **1.20 s**. The board's own timestamps:

| Tap | Card | Student | Board time | Gap since previous | Board said |
|---|---|---|---|---|---|
| 1 | `01 02 03 04` | CS-01 Alice Sharma | 15:31:01 | — | `GRANTED PRESENT` |
| 2 | `11 22 33 44` | CS-02 Rohit Verma | 15:31:02 | ≈ 0.2 s | `GRANTED PRESENT` |
| 3 | `55 66 77 88` | CS-03 Sara Khan | 15:31:02 | ≈ 0.2 s | `GRANTED PRESENT` **<<< PROXY SUSPECT** |
| 4 | `AA BB CC DD` | CS-04 Imran Qureshi | 15:31:02 | ≈ 0.2 s | `GRANTED PRESENT` **<<< PROXY SUSPECT** |
| 5 | `20 74 0B 56` | CS-05 Owner | 15:31:02 | ≈ 0.6 s | `GRANTED PRESENT` **<<< PROXY SUSPECT** |

Verbatim from the serial monitor:

```
[2026-11-09 15:31:02] Sara Khan      CS-03 GRANTED  PRESENT         <<< PROXY SUSPECT
{"uid":"55 66 77 88","name":"Sara Khan","roll":"CS-03","result":"GRANTED",
 "attendance":"PRESENT","suspect":true,"simulated":true,"ts":"2026-11-09T15:31:02","src":"ntp"}
         !! 3 different cards tapped within 2s - possible proxy attendance
```

**Note the fourth gap.** It stretched to roughly 0.6 s because each command has to wait for the
previous response to drain. That single number is the difference between this run scoring 58 and
scoring 65 — see §10. It is an artefact of driving the board over a serial port, not of the
scoring code.

---

## 6 · Layer 1 — the board's own check

The firmware keeps a small ring buffer of the **last 8 taps**: which roster slot and at what
`millis()`. On every accepted card it asks one question:

```c
static const uint32_t PROXY_WINDOW_MS = 2000;   // 2 s window
static const int      PROXY_DISTINCT  = 3;      // three different cards

int distinctScannersInWindow(uint32_t now) {
  uint32_t mask = 0;                            // one bit per roster slot
  for (int i = 0; i < recentCount; i++)
    if (now - recent[i].ms <= PROXY_WINDOW_MS) mask |= (1UL << recent[i].idx);
  return popcount(mask);
}

bool suspect = distinctScannersInWindow(now) >= PROXY_DISTINCT;
```

Why taps 3, 4 and 5 are flagged and 1 and 2 are not:

- after tap 1 → 1 distinct card → not flagged
- after tap 2 → 2 distinct cards → not flagged
- after tap 3 → **3 distinct** cards inside 2 s → flagged, and every later tap still sees three
  or more still inside the window → flagged again

The board does not judge, punish or block. It adds `"suspect": true` to the record and prints a
warning line. The door still opens — which is the correct behaviour for a prototype: false
positives must not lock real students out.

---

## 7 · The upload path

Each accepted tap became one JSON record and went into the on-board queue in LittleFS. The board
uploads every `FLUSH_EVERY_MS = 20000` (20 s) or immediately when told:

```
> upload
upload: attempted
> queue
queue: 0 pending
```

The receiver appended them to `server/data/events.ndjson`. One record, field by field:

| Field | Example | Meaning |
|---|---|---|
| `uid` | `55 66 77 88` | the card's factory serial number |
| `name`, `roll` | `Sara Khan`, `CS-03` | who that UID is registered to |
| `result` | `GRANTED` | in the roster → door opens |
| `attendance` | `PRESENT` | first time today |
| `suspect` | `true` | the board's own 3-in-2 s check fired |
| `simulated` | `true` | came from `sim`, not a physical card |
| `ts` | `2026-11-09T15:31:02` | device clock, NTP-synced (IST) |
| `src` | `ntp` | the clock was real, not uptime |
| `received_at` | `2026-11-09T15:31:04` | when the laptop wrote it (added by the server) |

---

## 8 · Layer 2 — the laptop's score

The receiver groups records **by day** into a session (`session_02` here), then calls
`detect.py`. The scoring works in three moves.

### 8.1 Find the run

`fast_runs()` cuts the day's grants into "maximal runs": any stretch where each consecutive gap
is **under 1.20 s** (`GAP_FAST`). Our five taps were all within 1.20 s of the previous one, so
they formed one run of five. Runs shorter than `MIN_RUN = 3` are ignored — two people walking in
together is normal.

### 8.2 Measure seven signals on that run

| Signal | What it measures | This run |
|---|---|---|
| `impossible-gap` | share of gaps under **0.50 s** — faster than two people can physically be | **0.75** (3 of 4) |
| `burst` | how many cards are in the run: `(n − 2) / 3` | **1.00** (5 cards) |
| `crowd-anomaly` | z-score of how unusual this many neighbours is *for this student* | **0.435** |
| `tight-gaps` | share of gaps in the ambiguous **0.50–1.20 s** band | **0.25** (1 of 4) |
| `order-rigidity` | how often this exact ordered chain has repeated before | **0.00** (never) |
| `new-cards` | share of cards never seen in earlier sessions | **0.00** |
| `nearby-denials` | unregistered cards within 15 s of the run start | **0.00** |

### 8.3 Weight them and add up

| Signal | Value | × weight | = points |
|---|---|---|---|
| impossible-gap | 0.75 | 0.40 | **0.300** |
| burst | 1.00 | 0.20 | **0.200** |
| crowd-anomaly | 0.435 | 0.12 | **0.052** |
| tight-gaps | 0.25 | 0.10 | **0.025** |
| order-rigidity | 0.00 | 0.10 | 0.000 |
| new-cards | 0.00 | 0.05 | 0.000 |
| nearby-denials | 0.00 | 0.03 | 0.000 |
| **raw total** | | | **0.577** |

Companion discount: `0.55 × habit × ambiguous`, where `habit` is how often these particular
people have walked in together. Here `habit = 0`, so the discount is **0** and is not printed.

```
(0.40x0.75 + 0.20x1.00 + 0.12x0.43 + 0.10x0.25 + 0.10x0.00 + 0.05x0.00 + 0.03x0.00)
  = 0.577  ->  58/100  REVIEW
```

Bands: `0–29 CLEAR · 30–49 WATCH · 50–69 REVIEW · 70+ HIGH`.

---

## 9 · What the number is actually saying

Read the winning terms out loud and the verdict writes itself:

> *"Five different cards were tapped inside one second — three of the four gaps were faster than
> two people can physically be — and these particular students are not usually together in that
> size a group."*

`REVIEW` means: **worth a human looking at the timestamps.** It does not mean anyone is guilty,
and the system never changes a record on its own.

---

## 10 · Why 58/REVIEW and not 71/HIGH

Two honest reasons, both visible in the arithmetic.

**1. One gap drifted past 0.5 s.** Three of four gaps were under the physical limit, so
`impossible-gap` earned 0.75 of its 0.40 weight — 0.300 instead of 0.400. If all four had been
under 0.5 s, the total would be **0.652 → 65 REVIEW**. That drift comes from serial turnaround:
each `sim` command waits for the previous output to drain.

**2. This was the first time this chain had ever been seen.** `order-rigidity` needs history, and
there was none, so it contributed nothing. On a cold day the ceiling for a five-card stack is
about `0.40 + 0.20 + 0.12 = 0.72` — and even that requires a maximum crowd-anomaly score.

This is not a weakness of the test, it is the design working as intended:

| Situation | What the score does |
|---|---|
| **First-ever** stacked run, on a fresh day | lands around **REVIEW 50–69** — a human should look |
| **Same chain repeated** on a later day | `order-rigidity` wakes up and pushes it to **HIGH 70+** |
| Habitual pair who always walk in together | companion discount pulls the score back down |

You can see case 2 in the shipped sample data: `session_05` scores **71 HIGH** with
`order-rigidity 0.60` because that exact chain had been seen three times before.

So: **a stack of cards is REPORT-worthy the first time and HIGH-severity the second time.** That
is the argument to put in the report — the system's real value is that repetition cannot hide.

---

## 11 · Layer 3 — the dashboard, with no reload

The page polls `/api/summary` every 2 s, compares a signature (`scans | sessions | students |
incidents | percentages`) and re-renders only when something changed. Measured on the open tab
immediately after the upload:

| Before | After | Meaning |
|---|---|---|
| Sessions **1** | **2** | a new day appeared as `session_02` |
| Scan rows **7** | **12** | the five burst records arrived |
| Flagged runs **0** | **1** | the incident was rendered |
| Students **1** | **5** | the five cardholders entered the roster view |
| `navigation` entries | **1** | the page never navigated or reloaded |

The card read, in the panel:

> **REVIEW** · **58**/100 · `session_02 · 2026-11-09 15:31:01`
> `CS-01` `CS-02` `CS-03` `CS-04` `CS-05` · 5 cards in 1.0 s
> • impossible-gap 75% of pairs under 0.5s • burst 5 cards in 1.0s • crowd-anomaly z-score 0.44

Under *show the calculation* the same seven rows from §8.3 appear, so anyone can audit the
number by hand. That is deliberate: **no score on the page is unexplained.**

---

## 12 · What was real, what was simulated

| Piece | Real? | How you know |
|---|---|---|
| The card `2E 63 64 F8` being registered | **real** — wrote to LittleFS over serial | `list` prints 6 cards; it survives a reboot |
| The UID → student lookup, attendance counters, LEDs, servo | **real firmware logic** | same `handleCard()` as a physical tap |
| The five taps themselves | **simulated** (`sim`), no radio involved | every record says `"simulated":true` |
| The queue and the upload | **real** — HTTP POST with the device token | `queue: 0 pending`, records in `events.ndjson` |
| The scoring | **real** `detect.py`, unmodified | the arithmetic above is the program's own output |
| The dashboard update | **real** browser, no reload | `navigation` entries = 1 |

**What this run cannot prove:** that the physical reader sees a fanned stack of real cards the
same way. That needs your hand and five cards — §13 tells you exactly what to expect.

---

## 13 · Doing it again with your hands

1. Power the board, open the dashboard on the laptop (`http://<laptop-ip>:8080/`).
2. Type `session` in the Serial Monitor — resets `PRESENT` so the run is clean.
3. Hold **five different registered cards** in one hand as a fan.
4. Fan them across the reader as fast as you can, **without lifting the whole stack away** —
   aim for five reads inside about a second.
5. Watch the Serial Monitor, then the dashboard. Do not touch the page.

**Expected:** taps 3–5 print `<<< PROXY SUSPECT`; within a couple of seconds a new run appears on
the dashboard; its band is usually **REVIEW 50–69** the first time.

| What you see | What it means | What to do |
|---|---|---|
| No incident at all | the taps took longer than 1.20 s apart, so no run formed | go faster; gaps are between *reads*, not between cards |
| `WATCH` (30–49) | only two gaps were under 0.5 s | squeeze the fan, closer to the antenna |
| `REVIEW` (50–69) | normal first-time stack | nothing — that is the intended result |
| `HIGH` (70+) | repeated chain, or extra signals | expected if you ran the same order on a previous day |
| `DENIED` instead of a grant | that card is not registered | `list`, then `register <uid> <roll> <name>` |

Do it on **two different days with the same card order** and you will see the band climb into
`HIGH` on its own — no code change, no extra hardware. That demonstration is the whole thesis.

---

## 14 · What this design still cannot do

- **A single slow tap of someone else's card is invisible.** One card, once, at normal speed looks
  exactly like that person walking in. No timing heuristic can separate it.
- **It cannot see bodies.** Tailgating through the door, or one person tapping and three walking
  in, produces no signal at all.
- **It cannot distinguish a stack from a stampede.** Five genuinely different people arriving in
  the same second would score the same. The system flags *patterns*, not people.
- **The verdict is a probability, not a proof.** `HIGH` means "treat as proxy until proven
  otherwise", and the word *until* matters: there is always a human in the loop.

The honest framing for the report: this is **tamper-evident attendance**, not cheat-proof
attendance. The value is that the cheap version of the attack (five cards in one hand) leaves a
signature that survives in the data even after the fact.

---

## 15 · Every term, once

| Term | Meaning |
|---|---|
| **UID** | the card's factory serial number, e.g. `20 74 0B 56`. Not secret, not changeable, cloneable. |
| **roster** | the table of registered cards on the board: UID → roll number + name. Lives in LittleFS, edited with `register` / `remove`. |
| **session** | one attendance day. `session` on the serial console or `SESSION_MS` clears everyone's `PRESENT`. |
| **`PRESENT`** | first accepted tap of the session for that student. |
| **`ALREADY_MARKED`** | a later tap by someone already counted — door opens, number unchanged. |
| **`GRANTED` / `DENIED`** | in the roster / not in the roster. `DENIED` never unlocks the door. |
| **`suspect`** | the **board's** 3-cards-in-2-s verdict, computed at tap time. |
| **`simulated`** | produced by `sim`, not by a physical card. |
| **queue** | records waiting in the board's flash to be uploaded. `queue` shows the count. |
| **`src`** | where the timestamp came from: `ntp` (real clock) or `uptime` (relative, `T+83s`). |
| **run** | a stretch of grants where every consecutive gap is under 1.20 s. |
| **`impossible-gap`** | gaps under 0.50 s — no two people can hand over that fast. |
| **`burst`** | how many distinct cards are in the run. |
| **`tight-gaps`** | gaps in 0.50–1.20 s: fast, but humanly possible. Weak evidence. |
| **`crowd-anomaly`** | z-score of the number of neighbours, compared with **that student's** history. |
| **`order-rigidity`** | how often this exact ordered sequence of cards has repeated. |
| **`new-cards`** | share of cards never seen before (could be new students). |
| **`nearby-denials`** | unregistered cards being tried around the same moment — probing. |
| **companion discount** | small subtraction when the same people habitually walk in together. |
| **band** | `CLEAR < 30`, `WATCH 30–49`, `REVIEW 50–69`, `HIGH 70+`. |

---

## 16 · Where the code is

| What | File · where |
|---|---|
| The proxy window and its 3-card rule | `rfid-attendance-door.ino` · `PROXY_WINDOW_MS`, `PROXY_DISTINCT`, `distinctScannersInWindow()` |
| One tap's whole decision | `rfid-attendance-door.ino` · `handleCard()` |
| The `sim` command | `rfid-attendance-door.ino` · console handler (`lower.startsWith("sim")`) |
| Thresholds, weights, bands | `analysis/detect.py` · `GAP_PHYS`, `GAP_FAST`, `MIN_RUN`, `WEIGHTS`, `BANDS` |
| Run finding and scoring | `analysis/detect.py` · `fast_runs()`, `score_run()` |
| Receiving, grouping by day, serving the page | `server/server.py` · `summarize()`, `do_POST()`, `do_GET()` |
| The dashboard itself | `analysis/dashboard_template.html` → generated `dashboard/report.html` |

---

## 17 · Housekeeping after the test

- The **five simulated records** were deleted from `server/data/events.ndjson`; the file keeps only
  hand-tapped scans. A copy of the pre-clean file is at `/tmp/events-before-clean.ndjson`.
- Two scans recorded after the test, at `15:36:55` (CS-05) and `15:36:59` (CS-06), are **real
  hand taps** — they are what a genuine registration looks like, and they stay.
- The roster keeps **6 cards**, including `2E 63 64 F8` / CS-06.
- To drop CS-06 again for a `DENIED` demo: `remove 2E 63 64 F8`, then put it back with
  `register 2E 63 64 F8 CS-06 Owner 2`.
- The scoring baseline (`analysis/state/model.json`) is learned state. Running `detect.py`
  repeatedly without `--no-learn` inflates it and changes scores; delete it and run once to get
  the documented numbers back.

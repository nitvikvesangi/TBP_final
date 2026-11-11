# Presenting this project

A runbook for the demo. Read it once, keep it open on the laptop, follow it top to bottom.
Quoted lines are what you say out loud; everything else is what you do or what you must see.

**The pitch in one sentence:** *a card reader that opens a door and marks attendance, plus a
scorer that catches one person tapping several cards to mark a whole row of friends present.*

**What earns the marks:** the second half. Anyone can read a card. Recognising that five cards
tapped in under a second is not five people is the actual contribution.

---

## 0 · The four claims, in order of strength

| Claim | The evidence you can show |
|---|---|
| It works as hardware | card → green LED, servo nudge, `GRANTED / PRESENT`; unregistered card → red LED, door stays shut |
| It records honestly | dashboard updates itself within ~2 s, no refresh; timestamps, scan source, per-student history |
| It catches proxy attendance | the 2026-11-09 stacked-tap run: 5 cards in 1.20 s → `REVIEW 58/100`, with the arithmetic on screen |
| It does not cry wolf | 8 sessions: **4/4 attacks caught, 0/4 false alarms**; the group of friends who walk in together stays silent |

---

## 1 · Ten minutes before

| Step | Command / action | Good sign |
|---|---|---|
| 1 | Plug the board in, `ls /dev/cu.*` | `/dev/cu.usbserial-0001` present |
| 2 | `./start.sh` (one command: receiver + browser) | `pid … `, `token: set (from secrets.h)`, `dashboard … (opening)` |
| 3 | The browser it opened: `http://127.0.0.1:8080/` | the register renders, ticker says **live** |
| 4 | Serial console at **115200** (`scripts/serial_live.py`) | `=== RFID Attendance + Door Access ===`, `rc522: ok`, `System Ready` |
| 5 | Type `list` | five cards, `CS-01` … `CS-05` — CS-06 stays out as the reject card |
| 6 | Type `queue` | `queue: 0 pending` on Wi-Fi; anything pending uploads by itself |
| 7 | Scan your card once, watch the dashboard | one new row appears without reloading — then the setup is proven |
| 8 | Free the serial port if a script complains | `PIDS=$(lsof -t /dev/cu.usbserial-0001); [ -n "$PIDS" ] && kill $PIDS` |

Two things to have open before you start: the **serial console** and the **dashboard**. You will
alternate between them, and the dashboard is proof that the board is not just printing text.

If the receiver is not running, the dashboard still opens — it shows its **saved copy** with a grey
dot. Say so rather than letting them think it is live.

`./start.sh --status` mid-demo answers "is it up, and is anything arriving?" in one line: the last
record with its roll, result and attendance. If it says `not running`, run `./start.sh` again — it
reuses anything already on the port. If it warns that the board uploads to a different address than
this laptop, that is the reason the dashboard is still: the sketch's `CLOUD_URL` is stale, and only a
re-upload fixes it. The door and the LEDs keep working meanwhile, so nothing is lost — say that out
loud instead of stalling.

---

## 2 · The opening — 60 seconds, say it roughly like this

> "Attendance is taken by a card reader at the door. One card, one person, one row — that part is
> solved and cheap. The unsolved part is the obvious cheat: one student holds five friends' cards
> and taps them one after another. The system records five present students, and nobody can tell.
>
> So the project is in two halves. The first half is the door: an ESP32, an RFID reader, a servo
> and two LEDs — it decides *may this card enter*, and it writes the attendance record with a
> timestamp. The second half is a scoring model that reads the sequence of taps and asks a
> different question: *could these taps really be different people?* Two different cards closer
> than half a second cannot be two people at one door.
>
> What I'll show you is the door working, then the record, then a run where five cards were tapped
> in 1.2 seconds and the system scored it 58 out of 100 and asked for a human review — with the
> arithmetic visible."

Then move to the hardware without pausing for questions. Questions at the end, or you will lose
the thread.

---

## 3 · Live hardware — 2 minutes

| Do | You should see | What it proves |
|---|---|---|
| Scan the **blue card** | `"result":"GRANTED","attendance":"PRESENT"`, green LED for 0.5 s, servo gives two short nudges | the door answers the card, the record answers attendance |
| Point at the servo | it pulses and settles; the latch is **not** held open | fail-safe: no power means no entry |
| Scan the **second card** (CS-06, deliberately unregistered) | `DENIED`, `door: stays LOCKED`, red LED 0.5 s | deny path is real, not a branch that never runs |
| Scan the **blue card again** | `GRANTED` + `ALREADY_MARKED` | one card cannot inflate its own count |
| Look at the dashboard | the new row slides in, `+1 new` flashes, ticker still **live** | the record follows the door without a refresh |**If you ever want both cards admitted again** — say, to demonstrate a second grant — put CS-06
back with `register 2E 63 64 F8 CS-06 Owner 2`, or `remove` whichever card you want to be the
reject card. The roster is written to flash, so either choice survives a power cycle. The NFC tag
`04 11 22 33 44 55 66` is a third, always-unregistered option if you would rather keep both cards
working.

**Say while the servo moves:** *"Two separate decisions, deliberately: the door decides entry, the record decides counting. If the reader dies, the door fails shut and the record is still consistent."*

If you want to show a stack tap without five cards, use the firmware's own path:

```
sim 11 22 33 44      (enter, then repeat twice more, quickly)
```

Taps 3+ print `<<< PROXY SUSPECT` — that is the **board's** own 2-second / 3-distinct-card check,
running on the same code path a real card takes. Say that explicitly: it is not a mock.

---

## 4 · The dashboard — 2 minutes

Open it and let them look before you talk.

> "It's built as a register, not a control panel — paper, hairlines, tabular numbers. The idea is
> that an attendance record should look like something you could sign."

Point at, in this order:

1. **The six gauges** — sessions, students, attendance, flagged runs, review-or-above, high severity.
2. **The student table** — percentage, days present, a flag count, and the eligible / below-75% pill.
   *(Two students sit at 50% and are marked below 75% — that pill is a policy flag, not a model output.)*
3. **Click a student** — the drawer opens with that person's sessions, arrival times and any runs
   they appear in. This is the detail an invigilator would actually use.
4. **The incident band** — each run with its score, band and reasons; click for the seven-signal
   breakdown with weights and points.
5. **The scan log** — every card, granted or denied, with the timestamp and where the clock came from.

**Say:** *"Nothing here needs a refresh. The page re-reads the receiver every two seconds, diffs the
result, and only redraws what changed — which is also why it never loses your scroll position or
your search box while you're looking at it."*

---

## 5 · Eight sessions, one at a time — 3 to 4 minutes

This is the part the examiner can follow without any hardware. Press **Sample data** (or `s`).
A banner appears saying the data is synthetic — leave it there, it is honest and it looks deliberate.

It opens on **session 1 of 8**. Each press of the button, `s`, `→` or **Next** advances one session;
**Prev** / `←` goes back; **All sessions** returns to the whole set; **Back to live** or `Esc` leaves.

Inside a single session the page changes on purpose: the student column becomes **Arrived** with
clock times, the pill becomes **present / absent** (a term percentage would be nonsense inside one
attendance window), the gauges become session / present / scans / flagged, and the incident band
shows only that session's runs. Say that out loud once — it shows the numbers are recomputed, not
filtered cosmetics.

Walk it like this:

| Press | On screen | Say |
|---|---|---|
| 1 | 14 scans · 14 of 16 present · 1 flagged **WATCH 30** | "Four cards in 2.3 seconds — fast, but no pair closer than half a second. It says WATCH, 30: unusual, not impossible. That restraint is the point." |
| 2 | 15 scans · 15 present · clean | "A normal hour. No flag." |
| 3 | 17 scans · 13 present · **REVIEW 63** | "Five cards in 0.95 s, and every gap under half a second. 0.40×1 + 0.20×1 + 0.12×0.24 = 0.629, so 63." |
| 4 | 13 scans · 13 present · clean | "Three friends arrive together, 0.5–1.2 s apart. Not flagged — they were learned as habitual companions." |
| 5 | 17 scans · 12 present · **HIGH 71** | "Same five cards, same order, second time. The rigid-chain signal now pays: 0.708." |
| 6 | 18 scans · 13 present · **HIGH 80**, kind **PROBING** | "No cards at all — five *rejected* cards in six seconds. Someone is trying credentials at the door: 0.55 + 0.05×5." |
| 7 | 12 scans · 12 present · clean | "Another quiet hour." |
| 8 | 16 scans · 12 present · **HIGH 71** | "Same chain seen twice before; rigidity is 0.571 and the crowd signal 0.43." |

Then press **All sessions**: 8 sessions, 16 students, 122 scans, 82% average, 5 flagged runs
(1 WATCH, 1 REVIEW, 3 HIGH).

**Say:** *"Sixty-three the first time, seventy-one when the same ring repeats, eighty when it is not
cards being shared but cards being guessed. The score is not a verdict — REVIEW and HIGH both mean a
human looks."*

The five rolls in the ring runs are the same every time — `CS-01, CS-03, CS-06, CS-09, CS-11` — which
is what the crowd and rigidity signals are for. Point that out if someone asks why a real ring looks
different from a one-off.

---

## 6 · The strongest evidence — the real stacked-tap run

This was done on the bench on **2026-11-09 at 15:31**, with the real board, real reader, real upload
path. Only the card taps were injected, because there are two physical cards in the room, not five.

| Layer | What happened |
|---|---|
| Roster | `CS-06` was registered first, so a five-card burst could be admitted |
| Taps | five different registered cards, `sim`, in **1.20 s** |
| Board | from tap 3 onward: `<<< PROXY SUSPECT` (its own 2 s / 3-distinct rule) |
| Upload | records queued offline, uploaded, `queue: 0 pending` |
| Receiver | scored `session_02` as **REVIEW 58/100** |
| Dashboard | went from 1 session / 7 scans to **2 sessions / 12 scans / 1 flagged**, on its own, no reload |

The arithmetic, exactly as the card shows it:

```
impossible-gap  0.75 × 0.40 = 0.300     3 of 4 gaps under 0.5 s
burst           1.00 × 0.20 = 0.200     5 cards in 1.20 s
crowd-anomaly   0.435 × 0.12 = 0.052    neighbours unlike this student's history
tight-gaps      0.25 × 0.10 = 0.025     1 of 4 gaps in the 0.5–1.2 s band
                                          ---------
                                           0.577  →  58 / 100  REVIEW
```

**If asked why 58 and not the 71 from the synthetic session:** because this run had one gap just over
half a second, so the impossible-gap signal scored 0.75 instead of 1.00. That is the model being
honest about weaker evidence, and `PROXY_TEST.md` §10 is the full answer.

---

## 7 · Numbers to have in your head

| Number | Meaning |
|---|---|
| **0.5 s** | two different cards closer than this cannot be two people at one door |
| **0.40** | weight of that signal — the largest of the seven |
| **63 → 71 → 80** | same cheat first time, repeated, then not cards but guesses |
| **4/4 caught, 0/4 false alarms** | on eight labelled sessions |
| **58 REVIEW** | the real bench run, five cards in 1.20 s |
| **82%** | average attendance in the synthetic set; 2 of 16 below 75% |

---

## 8 · Questions they will ask

**"Why RFID and not face recognition or fingerprints?"**
Cheap, offline, no biometric data stored, and it works with a glove on. Face recognition at a
classroom door also fails the moment two people walk in together — which is the same failure the
proxy detector exists to catch.

**"Isn't this just a card log?"**
The log is the easy half. The scored part — seven timing and context signals, weighted, with a
learned baseline — is the contribution. Open any incident and the arithmetic is on screen.

**"Is this machine learning?"**
No, on purpose. It is a transparent weighted model with a learned baseline (habitual companions,
repeated chains, per-student neighbour history). A neural network would be unexplainable, and this
has to survive an invigilator asking "why is my name here?".

**"Does it produce false accusations?"**
On the eight labelled sessions: four attacks, four clean, all caught, none flagged. The friend group
that always arrives together is the control, and it stays silent because those pairs were learned.

**"What is simulated?"**
The eight-session set comes from `analysis/simulate.py` and is labelled as such in the dashboard.
The 15:31 run used `sim` on the real board because there are two cards, not five. Everything else —
reader, door, LEDs, timestamps, upload, receiver, scoring — is real.

**"What is the Wi-Fi for?"**
Two things: the clock and the upload. With no network the door still works, timestamps fall back to
uptime, and records queue in flash until a connection appears.

**"Two cards only — can you even show a class?"**
Five cards are registered; your second personal card is deliberately left out of the roster so it
can be the reject card. `sim` injects scans through the same handler a real card takes. The dashboard then loads the eight-session set for the full 16-student
view. Nothing on screen is hand-written HTML.

**"Privacy?"**
A UID, a roll number, a timestamp. No images, no fingerprints, no location beyond "this door".

**"What about a slow cheat — one card every two seconds?"**
It defeats the half-second rule and will land in WATCH rather than HIGH. That limit is stated in the
report, and the fix is a second reader at a second door, where impossible travel becomes provable.

**"What would you do next?"**
Two readers for travel-time proof, a term of real data to re-run `--eval`, and signed records so the
log itself cannot be edited afterwards.

---

## 9 · If something breaks

| Symptom | Fastest fix |
|---|---|
| `rc522: NOT detected` | reseat the 3.3 V / GND / SPI wires; confirm 3.3 V, never 5 V |
| Board resets when the servo moves | servo on its own 5 V supply, grounds joined |
| Dashboard dot grey, "saved copy" | receiver not running — restart it, then press **Live** |
| Dashboard shows sample data and you wanted live | **Back to live** (or `Esc`) |
| Serial console refuses to open | something holds the port: `lsof -t /dev/cu.usbserial-0001` and kill that PID |
| Card scans but nothing on the dashboard | check the token and that the board and laptop are on the same network; `queue` will show records waiting |
| You have three minutes only | skip §4 and §5; do §3 (four scans), then §6 (the 58 REVIEW card and its arithmetic) |

---

## 10 · What is honestly not finished

Say these before they are found, not after.

- **Physical evidence is thin on purpose:** two cards, nine real scans across two days. The 8-session,
  122-scan dataset is generated, and the report says so.
- **The 82% and the precision/recall come from my own generator.** They show the model does what it
  was built to do; they are not a claim about a real college.
- **One doorway only.** The strongest version of this needs two readers.
- **A patient, irregular cheat still slips through** to WATCH instead of HIGH.
- **`detect.py` learns as it runs** — re-running it without `--no-learn` changes the documented
  numbers. Regenerate the dashboard from the committed `report.json`.
- **No firmware unit tests**, and the project is not under version control.

---

## 11 · Which file to open if they ask

| They ask | Open |
|---|---|
| "Show me the write-up" | `REPORT.md` |
| "How is it wired / how do I run it" | `README.md` |
| "One page I can hold" | `CHEATSHEET.md` |
| "Prove the 58" | `PROXY_TEST.md` |
| "How does the scoring work" | `analysis/README.md`, then `detect.py --explain` |
| "What is the state of the machine" | `HANDOFF.md` |
| "What do I say" | this file |

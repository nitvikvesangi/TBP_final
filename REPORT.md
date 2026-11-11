# RFID-Based Smart Attendance Management & Door Access Control

**Theme:** Cybersecurity & Digital Forensics
**Hardware:** ESP32 + MFRC522 RFID reader + SG90 servo
**Cost of core parts:** under ₹1000

---

## At a glance

- **One scan does two jobs** — the door unlocks **and** attendance is recorded.
- **Works with no internet.** Records are queued in flash and uploaded later.
- **Rejects unknown cards** — door stays locked, attempt is logged.
- **Flags proxy attendance** using a risk score, not a single fixed rule.
- **Learns from past sessions**, so repeated cheating scores higher each time.
- **Does not punish friends** who always walk in together.

---

## 1. What problem it solves

- Manual roll-call wastes class time and has transcription errors.
- Keys/cards alone can't prove **who is holding the card** → proxy attendance.
- College Wi-Fi with a login page can't be used by an ESP32 → hotspot or offline needed.

**Our answer:** automate the record, keep the door controlled, and **flag suspicious patterns instead of pretending the card proves identity**.

---

## 2. Block diagram

```
   RFID card  ->  MFRC522 reader  ->  ESP32  ->  servo (door lock)
                                       |
                                       +-> attendance record (timestamp)
                                       +-> flash queue -> optional cloud
                                       |
                                  analysis engine -> dashboard
```

---

## 3. Hardware list

| Part | Purpose | Note |
|---|---|---|
| ESP32 | main controller | Wi-Fi + flash built in |
| MFRC522 | reads 13.56 MHz card UID | **3.3 V only** — 5 V damages it |
| RFID cards (1–2) | credentials | enough for the demo |
| SG90 servo | drives the latch | use external 5 V if board browns out |
| Green + red LEDs | access feedback at the door | 220–330 Ω series resistor each |
| 470 µF capacitor | steadies the 5 V rail | stops brown-out when the servo turns |
| Breadboard + wires | assembly | — |

**No** IR sensor, buzzer, LCD or keypad is required.

---

## 4. Wiring

| MFRC522 | ESP32 | | Servo | ESP32 |
|---|---|---|---|---|
| SDA (SS) | GPIO 5 | | Signal | GPIO 13 |
| SCK | GPIO 18 | | V+ | 5 V (external ok) |
| MOSI | GPIO 23 | | GND | GND |
| MISO | GPIO 19 | | | |
| RST | GPIO 22 | | | |
| 3.3V | 3V3 | | | |
| GND | GND | | | |

| Indicator | ESP32 | Meaning |
|---|---|---|
| Green LED (via 220–330 Ω) | GPIO 26 | 0.5 s pulse on an accepted scan |
| Red LED (via 220–330 Ω) | GPIO 27 | 0.5 s flash on a refused card |

**Common ground** between servo supply and ESP32 is mandatory.

---

## 5. How one scan works

1. Card comes near the reader → MFRC522 reads its **UID**.
2. ESP32 compares the UID with the registered list.
3. **Unknown UID** → door stays **locked**, event logged as `DENIED`.
4. **Registered UID** → green pulse, and the servo gives a short **two-pulse nudge** as the latch acknowledgement. The latch is deliberately **not** held open.
5. The nudge self-cancels in about 0.7 s, so nothing stays energised and the reader is free to poll again immediately — which keeps the read timing the proxy heuristic depends on intact.
6. Attendance written **once per session** with a timestamp.
7. If the same card is scanned twice quickly → **no double counting**.
8. Green LED pulses 0.5 s to confirm the scan; a refused card flashes red for the same 0.5 s. Both LEDs report the *scan*, not the door.
9. Record goes to flash queue → uploaded when Wi-Fi exists.

**Key point:** authorization and attendance are **separate decisions**.
A student who is already marked present still gets the door opened — the door
answers *"may this card enter?"*, the record answers *"is this attendance counted?"*.

---

## 6. What is actually new here

- **Two outputs from one scan** — most student projects do either a door lock *or* attendance.
- **Physics instead of a magic number.** Two different cards read under **0.5 s** apart cannot be two people walking through one doorway. That's the anchor.
- **Companion discount.** Friends who always arrive together are *learned* as a pair, so their normal fast entry is **not** flagged.
- **Recurring offense gets worse.** The same ordered card sequence repeating across sessions raises the score (63 → 71 → HIGH). A wallet has a fixed card order; people don't.
- **Honest about limits.** Card cloning is undetectable at UID level, and the report says so.

---

## 7. The risk model (7 signals → 0–100)

| Signal | Weight | Plain meaning |
|---|---|---|
| impossible gap | 0.40 | cards read closer than 0.5 s — physically too fast |
| burst size | 0.20 | how many cards in the run |
| crowd anomaly | 0.12 | more neighbours than *this student* usually has |
| tight gaps | 0.10 | 0.5–1.2 s (“fast friends, or tapping”) |
| order rigidity | 0.10 | same exact chain seen before |
| new cards | 0.05 | cards never seen in any session |
| nearby denials | 0.03 | unknown cards rejected at the same moment |

**Bands:** `CLEAR < 30 ≤ WATCH < 50 ≤ REVIEW < 70 ≤ HIGH`

**Nothing is hidden in the maths.** Every incident can show its own working:

- each signal's **value** (0–1), its **weight**, and the **points** it added
- the **raw total**, the **companion discount**, and the **final score**
- the **date and time** of the run, taken from the device's own log
- one line of arithmetic, e.g. `(0.40x1.00 + 0.20x1.00 + 0.12x0.24 + ...) = 0.679 -> 68/100 REVIEW`

See it with `--explain` in the terminal, or **“show the calculation”** on the dashboard.

**Separate incident type:** 3+ `DENIED` cards within 15 s → **PROBING** (someone trying random cards).

**The clever bit:** the companion discount only cancels the *ambiguous* signals.
Impossible gaps are never excused — no friendship explains 0.2 s.

---

## 8. Measured results

8 synthetic sessions, 16 students, one repeating proxy ring, one probing session,
plus 3 friends who always arrive together:

| Session | Truth | Result |
|---|---|---|
| 01, 02, 04, 07 | clean | **no alarms** |
| 03 | proxy | 63/100 REVIEW |
| 05 | proxy | 71/100 HIGH |
| 06 | probing | 80/100 HIGH |
| 08 | proxy | 71/100 HIGH |

- **caught 4/4 attack sessions**
- **0 false alarms on 4 clean sessions**
- precision 1.00, recall 1.00
- **Friends case:** 4 sessions contain real 0.5–1.2 s three-friend runs → **none reached WATCH**

**Read the trend, not just the totals:** the first attack is REVIEW, repeats
become HIGH. That is the model learning.

---

## 9. Dashboard

`dashboard/report.html` — one file, opens in any browser, no server.

Shows:

- attendance **% per student** with 75% eligibility
- **flagged incidents** with score, band, cards involved and reasons
- **session timeline** with red ticks where a run was flagged
- a **payload JSON** loader to inspect another run

Regenerate with:

```bash
python3 detect.py --state state/model.json --dashboard ../dashboard/report.html
```

---

## 10. Cybersecurity & Digital Forensics relevance

**Security side**

- **Authentication** — only registered UIDs pass.
- **Authorization** — separate decision from attendance.
- **Access control** — physical entry granted/denied, logged either way.
- **Anomaly detection** — behavioural monitoring of the access stream.

**Forensics side**

- Every attempt logged: **granted, denied, duplicate, flagged**.
- Timestamps from **NTP**; if offline, marked `"src":"uptime"` — honest, not faked.
- **Tamper-evident chain:** device → flash queue → server, in order.
- Audit trail answers *"who entered, when, and what looked unusual"*.

**Limitations to state openly**

- UID is **not** a cryptographic identity — a cloned card works.
- Logs are **not tamper-proof** without server-side signing.
- A **slow, irregular** stack tap can still slip below the physics rule.

---

## 11. SDG mapping

- **SDG 9** — affordable IoT infrastructure for automation.
- **SDG 16** — accountability through reliable, auditable records.

---

## 12. Demo script (5 minutes)

| Step | Do | Shows |
|---|---|---|
| 1 | Power up with hotspot on | `rc522: ok`, `ntp: ok`, `System Ready` |
| 2 | Scan registered card | door **unlocks**, `GRANTED / PRESENT` |
| 3 | Wait 5 s | door **relocks** |
| 4 | Scan unregistered card | `DENIED`, door stays **locked** |
| 5 | Scan same card again | `ALREADY_MARKED`, no double count |
| 6 | `sim 11 22 33 44` ×3 fast | `<<< PROXY SUSPECT` |
| 7 | `list` | roster + present count |
| 8 | `queue` / `dump` | pending records, exportable |
| 9 | Open dashboard | % + incidents |

**Trick to remember:** with 2 cards you still demo a full class — `sim` injects
fake scans through the real code path.

---

## 13. Files

| File | What it is |
|---|---|
| `rfid-attendance-door.ino` | firmware: door + attendance + flash roster + queue |
| `server/server.py` | laptop receiver + live dashboard (token-protected) |
| `CHEATSHEET.md` | one-page bench sheet: commands + expected numbers |
| `README.md` | wiring, setup, commands, tuning |
| `REPORT.md` | this document |
| `HANDOFF.md` | build state, environment quirks, verified results, open issues |
| `scripts/` | host-side flashing + serial helpers (broken macOS serial driver) |
| `led_test/` | LED pin sweep used to diagnose the indicator wiring |
| `rc522_test/` | reader-only wiring test |
| `analysis/detect.py` | risk engine (scores incidents) |
| `analysis/simulate.py` | labelled synthetic sessions |
| `analysis/import_serial.py` | raw Serial Monitor capture -> clean NDJSON |
| `analysis/tests.py` | 14 regression tests for the scoring rules |
| `analysis/README.md` | model details + limits |
| `analysis/dashboard_template.html` | dashboard source |
| `dashboard/report.html` | generated dashboard |
| `wokwi/` | hardware-free simulation |

---

## 14. Likely viva questions

- **“How do you stop proxy attendance?”** → You can't stop it with a card; you *detect* it. Physics gap + order rigidity + history, then flag for review.
- **“Why not biometrics?”** → Cost and privacy; we keep it non-biometric and say what it can't do.
- **“Why 0.5 s?”** → One doorway passes roughly a person per 0.6 s. Two different cards inside 0.5 s is not two people.
- **“Friends who enter together?”** → Learned as companions; only the ambiguous signals are discounted.
- **“What if the cheat taps slowly?”** → It can pass; that's a stated limitation, and crowd-anomaly/order-rigidity still nudge it into WATCH.
- **“Is this real data?”** → Hardware run proves the path; multi-student evaluation uses a labelled generator, stated openly.
- **“Why offline queue?”** → Campus Wi-Fi needs a login page, so the device must not depend on it.
- **“How do you know a change didn't break the detector?”** → 14 regression tests cover the physics rule, the companion discount, probing, timestamps and the payload. `python3 -m unittest tests -v`

---

## 15. Future scope

1. **Second reader** at another door → impossible-travel detection.
2. **MIFARE DESFire / challenge-response** → beat cloning.
3. **Server-side signed logs** → tamper evidence.
4. **Notifications** on HIGH incidents.
5. **Remote card registration** without reflashing.
6. **Real data collection** to retune weights.

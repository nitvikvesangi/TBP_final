# VIDEO SCRIPT — Theme Based Project submission

> **Short version exists now:** `video/explainer.mp4` is a 2 min 51 s plain-language explainer
> (11 slides, AI narration, built by `video/build_video.py`). Use it for the explanation half and
> drop your hardware footage into the demo section. The 8-minute runbook below is the full plan
> if you present live or want to film a longer submission.

Everything you say, in order, with what to show while you say it. Target length **8 minutes**
(the sections below add up to ~7:30, which leaves room for one stumble).

Companion file: **`video/slides.html`** — open it, press `f` for fullscreen, `→` to advance.
Record that with your screen recorder and talk over it, then cut your hardware footage into
sections 3 and 4. Or ignore the deck and just use the narration.

---

## 0 · Before you press record

| Check | Command / action |
|---|---|
| Board plugged in, data cable | `ls /dev/cu.*` → `/dev/cu.usbserial-0001` |
| Receiver running | `./start.sh` → `token: set`, `dashboard … (opening)` |
| Dashboard open and **live** | `http://127.0.0.1:8080/` — ticker says `live · updated Ns ago` |
| Serial console open at 115200 | `/tmp/espvenv/bin/python scripts/serial_live.py` |
| `list` shows 5 cards | `CS-01` … `CS-05`; keep CS-06 (`2E 63 64 F8`) **out** as the reject card |
| Camera / phone charged, lens clean | film the servo and LEDs from ~40 cm, light from the side |
| Nothing else on the desk | the wires read as one mess on camera; clear the background |
| Free the serial port before any demo script | `PIDS=$(lsof -t /dev/cu.usbserial-0001); [ -n "$PIDS" ] && kill $PIDS` |

**Record in this order:** slides + narration first (you can re-record a slide), hardware second
while it is set up and working, dashboard third. Cut them together at the end. Never try to do
all three in one take — the board booting is the only thing that has to be live.

**Title for YouTube (exact format):**

```
Theme Based Project – Batch No – RFID-Based Smart Attendance & Door Access Control
```

Replace `Batch No` with your batch number. Set visibility **Public** or **Unlisted**, never Private.

---

## 1 · Problem introduction — 0:00 → 1:10

**Show:** slide 1 (title), then slide 2 (the problem). If you have a photo of a roll-call
register or your college corridor, put it here.

**Say, roughly word for word:**

> "This is our Theme Based Project — an RFID based smart attendance system with door access
> control. In most colleges attendance is still taken by calling out roll numbers. That costs
> five to ten minutes of every class, and it is easy to make mistakes while copying it into a
> register.
>
> One card per student solves the paperwork. But it creates a bigger problem. A card proves that
> a card was scanned — not who was holding it. One student can carry five friends' cards, tap
> them one after another at the door, and every one of those friends is marked present. That is
> proxy attendance, and a normal card log cannot see it at all.
>
> So our objective was two things. First, automate the record at the door and control the door
> itself. Second, detect the *pattern* of fake attendance instead of pretending the card proves
> identity. The system never accuses anyone and never marks anyone absent — it flags a run of
> taps for a human to review."

---

## 2 · Components and resources — 1:10 → 2:30

**Show:** slide 4 (hardware) and slide 5 (software), cutting to the physical parts on the table
as you name each one. Hold each part up before you talk about it, then put it down.

**Say:**

> "The hardware is five parts and a breadboard. The controller is an ESP32 DevKit: dual core,
> 240 megahertz, built-in Wi-Fi, four megabytes of flash, and 3.3 volt logic. The flash matters
> more than the Wi-Fi — the board keeps its registered cards and its unsent attendance records
> in flash, so it works with no laptop and no network.
>
> This is the MFRC522 reader. It works at 13.56 megahertz and reads the UID of ISO 14443A cards
> and tags over SPI. It runs on **3.3 volts only** — five volts destroys the module. Our module
> reports firmware version 0x82, which is a clone of the genuine chip; it reads cards correctly,
> and we say so honestly in the report.
>
> This small servo is the door latch. Its signal wire goes to GPIO 13 and it is powered from the
> 5 volt rail. A 470 microfarad capacitor across that rail stops the board from browning out the
> moment the motor starts — that was a real fault we had to fix.
>
> Two LEDs give feedback at the door: green for granted, red for denied, each with a 220 to 330
> ohm series resistor so the pin is not over-driven. Plus a breadboard, jumpers, and two cards.
>
> On the software side: the firmware is Arduino C++, compiled with arduino-cli for the ESP32. The
> receiver is a Python file with no dependencies at all, and the dashboard is one self-contained
> HTML file. There is no cloud account and no database anywhere in the system. Total cost of the
> core parts is under one thousand rupees."

---

## 3 · Assembly and architecture — 2:30 → 4:00

**Show:** the wired breadboard, then slide 6 (block diagram), then slide 7 (one scan, step by
step). Point at wires as you name the pins — do not read a table aloud.

**Say (wiring, while pointing):**

> "The reader connects over SPI: SDA to GPIO 5, clock to 18, MOSI to 23, MISO to 19, reset to 22,
> and — this is the one that kills modules — 3.3 volts, never 5. The servo signal goes to GPIO
> 13 with a common ground to the ESP32, and the LEDs sit on GPIO 26 and 27 through their
> resistors.
>
> The architecture is two separate decisions, deliberately kept apart. The **door** decision is
> local and instant: is this UID in the roster? Yes — green, and the servo gives a short
> two-pulse nudge on the latch. No — red, and the latch never moves. The **attendance** decision
> is the record: one entry per student per session, time-stamped, because a second tap in the
> same session says ALREADY_MARKED instead of counting twice.
>
> Each scan then goes into a queue in flash and is uploaded over Wi-Fi to the laptop receiver,
> which appends it to a log. A scoring model reads that log, and the dashboard renders both. If
> the network or the laptop is missing, nothing is lost — the door still works and the records
> wait in flash until the receiver is reachable."

---

## 4 · Working demonstration — 4:00 → 7:00

This is the section that earns or loses marks. Film the hardware **and** the screen in the same
frame if you can (phone on a stand behind the laptop), otherwise cut between them.

**Shot 4a — boot (20 s).** Power up / press reset with the serial console visible.

> "On boot the board reports the reader, its flash, the roster and the network:
> `rc522: ok`, `flash: ok`, `roster: 5 cards`, `wifi: connected`, `ntp: ok`, `System Ready`.
> NTP is only for the clock — without it the record still happens, but the time is labelled as
> seconds since power-on instead of a fake date."

**Shot 4b — granted (25 s).** Tap the registered card. Hold the frame on the LEDs and servo.

> "That is a registered card: GRANTED, attendance PRESENT, green LED pulses for half a second,
> and the servo gives two short nudges instead of holding the latch open. That is a deliberate
> safety choice — the door is never energised for longer than a pulse."

**Shot 4c — denied (20 s).** Tap the second card, which is deliberately left out of the roster.

> "This second card was never registered. DENIED, red LED, door stays shut — and the attempt is
> still logged. A refusal is evidence too."

**Shot 4d — no double count (15 s).** Tap the registered card again.

> "Same card again: GRANTED, but ALREADY_MARKED — one card cannot inflate its own attendance."

**Shot 4e — proxy detection, the point of the project (45 s).** Either fan your two cards plus
the NFC tag quickly, or run the firmware's own path on camera:

```bash
/tmp/espvenv/bin/python scripts/proxy_demo.py
```

> "Now the actual problem. Three different cards were tapped within two seconds. The board prints
> PROXY SUSPECT on its own — this is the same code path a real card takes, only the reader is
> bypassed, because we have two physical cards and not five. That is the firmware's simple rule:
> three distinct cards inside two seconds is faster than three people can walk through one door."

**Shot 4f — dashboard (60 s).** Cut to the dashboard. Point, do not read.

> "The dashboard is a register, not a control panel. Six headline numbers: sessions, students,
> attendance percentage, flagged runs, review-or-above, high severity.
>
> Notice it updated by itself — the page re-reads the receiver every two seconds and only redraws
> what changed, so nothing here needs a refresh. The scan log at the bottom has every scan with
> the timestamp the board stamped it with, and it says where that clock came from.
>
> Click any student and you get their sessions, arrival times and any flagged run they appear in.
> Open a flagged run and the arithmetic is on screen — signal, value, weight, points — so any
> number can be checked by hand."

**Shot 4g — the eight-session walkthrough (45 s, optional but strong).** Press **Sample data**
(`s`), then `→` twice to session 3, then twice more to session 5.

> "These eight sessions are a synthetic, labelled set — the banner says so, and it is labelled
> because we only own two cards. Session 3: five different cards in under one second, every gap
> below half a second — REVIEW, 63 out of 100. Session 5: the same cards in the same order a
> second time — HIGH, 71. Repeat cheating scores higher because the sequence itself has become
> evidence. Across the set: four attacks caught, four clean sessions, zero false alarms."

**Say once, before finishing this section:**

> "The Wi-Fi is only the clock and the upload. With the network off the door, the LEDs, the servo
> and the attendance all still work, and the records queue in flash."

---

## 5 · Conclusion — 7:00 → 8:00

**Show:** slide 11 (results), then slide 12 (limits and future scope).

**Say:**

> "To summarise what works. One tap does two jobs — it decides the door, and it writes an honest,
> time-stamped attendance record. The board runs with no internet and no laptop. Unknown cards
> are refused and logged. And the part that is the actual contribution: the system measures the
> *timing* of taps, so a stack of cards fanned in under a second is not mistaken for five people
> walking in, while a real queue of students is left alone.
>
> On our labelled eight-session set that is four attacks caught with zero false alarms, and a
> repeated cheat scores higher than a first-time one.
>
> We are honest about the limits. RFID reads a UID, so a cloned card carries the same identity —
> catching that needs strong authentication like DESFire or a second factor. One door cannot prove
> travel time, so a patient cheat one card every two seconds lands in WATCH instead of HIGH. And
> our multi-student evaluation is a labelled generator, not a term of real data.
>
> Next steps would be: a second reader at a second door, so impossible travel becomes provable; a
> term of real sessions to re-train and measure; and signed records so the log itself cannot be
> edited after the fact. Thank you — we are happy to take questions."

---

## 6 · Section-to-rubric map (check before uploading)

| Required point | Covered in | Visible evidence |
|---|---|---|
| Problem statement + relevance | 0:00–1:10 | slides 2, proxy-attendance example |
| Objective | 0:00–1:10 | slide 3 |
| Components/resources + specs | 1:10–2:30 | slides 4–5, parts on the table |
| Step-by-step assembly | 2:30–4:00 | wired breadboard, pin-by-pin pointing |
| System architecture / block diagram / workflow | 2:30–4:00 | slides 6–7 |
| Working demonstration + key features | 4:00–7:00 | card scans, LEDs, servo, terminal, dashboard |
| How it solves the problem | 4:00–7:00 | proxy run → flagged run with arithmetic |
| Conclusion | 7:00–8:00 | slides 11–12 |

---

## 7 · Copy-paste description for YouTube

```
Theme Based Project – Batch No – RFID-Based Smart Attendance & Door Access Control

An ESP32 + MFRC522 + SG90 door controller where one card tap both unlocks the door and writes a
time-stamped attendance record. The project's focus is proxy attendance: one student tapping
several friends' cards. A weighted model scores each run of taps from seven timing and context
signals, and flags it for review instead of accusing anyone.

Chapters
0:00 Problem introduction
1:10 Components and resources
2:30 Assembly and system architecture
4:00 Working demonstration
7:00 Conclusion and future scope

Sections: problem/objective, components with specifications, assembly and block diagram, live
card demonstration (granted, denied, no double counting, proxy burst), live dashboard, results
(4/4 attacks caught, 0/4 false alarms on a labelled set), limitations and future scope.

Hardware: ESP32 DevKit, MFRC522 (13.56 MHz, 3.3 V), SG90 servo, two LEDs, 470 uF capacitor.
Software: Arduino C++ firmware with an offline flash queue, a dependency-free Python receiver,
and a single-file HTML dashboard.
The eight-session dataset shown is synthetic and labelled as such; all hardware, timestamps,
upload and scoring are real. No biometric data is stored — only UID, roll number and time.
```

---

## 8 · If a take goes wrong

| Symptom | Fix |
|---|---|
| `rc522: NOT detected` | reseat 3.3 V / GND / SPI; confirm 3.3 V, never 5 V |
| Board resets when the servo moves | servo on its own 5 V supply, grounds joined |
| Dashboard dot is grey | receiver not running — `./start.sh`, then press **Live** |
| Dashboard shows sample data mid-demo | **Back to live** or `Esc` |
| Serial script says port busy | `lsof -t /dev/cu.usbserial-0001` then kill that PID |
| Card scans but nothing appears | check token and that board and laptop are on the same network; `queue` shows the backlog |
| No time for a re-take | cut section 4g; sections 4b/4c/4e/4f carry the marks |

`PRESENTATION.md` has the deeper Q&A, `CHEATSHEET.md` the one-page bench reference.

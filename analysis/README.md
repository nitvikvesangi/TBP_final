# Proxy-attendance risk model

The firmware's own `suspect` flag is a single fixed rule: three cards in five
seconds. That is easy to script around and easy to false-alarm on. This folder
replaces it with a weighted, *learning* model that reads the same NDJSON log the
ESP32 writes.

```
ESP32 log (ndjson)  ->  detect.py  ->  incidents with score + reasons
                            |
                     state/model.json   (baselines learned from past sessions)
```

Pure standard-library Python 3. No dependencies, no server.

---

## 1. The anchor: physics, not statistics

A single doorway passes roughly one person per 0.6 s. So:

| Gap between two **different** cards | Reading |
|---|---|
| `< 0.5 s` | **Impossible for two people.** Near-certain stack tap. Largest weight. |
| `0.5 – 1.2 s` | **Ambiguous.** Fast friends, or rapid tapping. Needs the learned baseline. |
| `> 1.2 s` | Normal walking pace. Not part of any run. |

Starting from a physical limit instead of an arbitrary threshold is what makes
the model defensible: it does not guess where "too fast" begins, it derives it.

---

## 2. Signals and weights

Each incident is a *run* of three or more grants whose consecutive gaps are all
under 1.2 s. The run is scored 0–100 from seven signals:

| Signal | Weight | What it measures |
|---|---|---|
| `phys` | 0.40 | fraction of gaps below the 0.5 s physical limit |
| `burst` | 0.20 | how many cards are in the run |
| `ctx` | 0.12 | how many neighbours this student usually has, **vs their own history** (robust z-score) |
| `tight` | 0.10 | fraction of gaps in the ambiguous 0.5–1.2 s zone |
| `rigid` | 0.10 | how often this **exact ordered chain** has appeared before — a wallet has a fixed card order, people do not |
| `new` | 0.05 | cards never seen in any previous session |
| `denied` | 0.03 | unregistered cards rejected around the same moment |

Bands: `CLEAR < 30 ≤ WATCH < 50 ≤ REVIEW < 70 ≤ HIGH`.

Separately, **three or more `DENIED` events within 15 s** raises a `PROBING`
incident — someone trying unknown cards, which is a different behaviour from
proxy attendance and is logged as such.

---

## 3. The companion discount — and why groups of friends are not flagged

This was the obvious flaw: friends who always walk in together look exactly
like a stack tap if all you measure is "three scans close together".

The model learns, per pair of students, how often they arrive adjacent within
the ambiguous zone. If two or three students are *always* adjacent at human
walking speed, that is companionship, and the ambiguous-zone evidence is
multiplied down by up to 55%:

```
score -= 0.55 * habit * (tight + ctx + rigid contributions)
```

Two deliberate details:

- **`phys` and `burst` are never discounted.** If the gaps are physically
  impossible, no amount of habit explains them.
- **Companionship is only learned from humanly possible gaps** (0.5–1.2 s).
  Without that rule the model is self-defeating: a cheat that repeats every
  session teaches it "these five students always arrive together" and earns
  itself a discount. This was a real bug found in testing — before the fix the
  April attack was getting a 50% discount.

That is the idea worth presenting: *repetition alone is ambiguous — it means
companionship or an assembly line depending on whether the timing is human.*

---

## 4. Usage

```bash
cd analysis

# make labelled synthetic data (no hardware needed)
python3 simulate.py --sessions 8

# score sessions in order, learning a baseline as it goes
python3 detect.py --state state/model.json --min-band REVIEW

# score one file without learning from it
python3 detect.py data/session_08.ndjson --state state/model.json --no-learn

# show the full arithmetic behind every score
python3 detect.py data/session_05.ndjson --state state/model.json --explain

# measured precision / recall against the labels
python3 detect.py --eval --state /tmp/st.json

# audit tables for the report appendix
python3 detect.py --state state/model.json --min-band REVIEW --csv audit

# regression tests for the scoring rules (14 of them)
python3 -m unittest tests -v

# turn a raw Serial Monitor capture into clean NDJSON
python3 import_serial.py capture.txt -o data/session_real_01.ndjson
```

Real logs from the ESP32 work unchanged: `event_time()` accepts the ISO
timestamp, or `T+42s` when the board had no NTP (in that case timing is still
exact, only the wall-clock label is relative).

---

## 5. Measured results

Eight synthetic sessions, 16 students, one repeating proxy ring (same four
victims plus a collector every time), one probing session, and a group of three
friends who always arrive together.

```
session             truth    incidents     verdict
session_01.ndjson   clean    -             clean
session_02.ndjson   clean    -             clean
session_03.ndjson   proxy    63/100 REVIEW caught
session_04.ndjson   clean    -             clean
session_05.ndjson   proxy    71/100 HIGH   caught
session_06.ndjson   probing  80/100 HIGH   caught
session_07.ndjson   clean    -             clean
session_08.ndjson   proxy    71/100 HIGH   caught

caught 4/4 attack sessions   false alarms 0/4 clean sessions
precision 1.00   recall 1.00
```

Two things to read from that table rather than the headline numbers:

- **The score rises with history.** 63 → 71 once the same ordered chain has
  been seen before; `rigid` only pays off after the ring repeats. A first-time
  offender is flagged as `REVIEW`, a repeat offender as `HIGH`.
- **The friend group stays silent.** Four of the sessions contain genuine
  0.5–1.2 s three-friend runs; with the learned baseline none of them reach
  `WATCH`, because the pairs were learned as habitual companions.

### Honest caveats

- These numbers come from **my own generator**, not real attendance data. They
  demonstrate that the model does what it was built to do; they do not prove
  real-world accuracy. Collect a few real sessions and re-run `--eval`.
- The 0.5 s limit assumes one doorway. Two readers at separate doors would add
  a much stronger signal (impossible travel), and would make the model more,
  not less, accurate.
- **A patient cheat defeats the physics rule** by tapping one card every two
  seconds. That is why `ctx` and `rigid` exist, and why the model reports
  `WATCH` instead of silently passing — but a slow, irregular stack tap can
  still slip through. Say so in the report.
- UID authentication still cannot prove *who* holds the card; this layer
  detects *behaviour associated with proxy attendance*, not identity.

---

## 6. Tuning

| Constant | Where | Effect |
|---|---|---|
| `GAP_PHYS` | `detect.py` | lower = more conservative, fewer impossible-gap hits |
| `MIN_RUN` | `detect.py` | 3 is the minimum that meaningfully differs from a pair |
| `WEIGHTS` | `detect.py` | redistribute if you collect real data |
| `COMPANION_DISCOUNT` | `detect.py` | 0.55 = companions can cancel a bit over half the ambiguity |
| band floors | `BANDS` | move `REVIEW` down to 45 if you want more sensitivity |

Tune against `--eval`, and use `--no-learn` while tuning so the baseline does
not drift between runs.

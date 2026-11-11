# Video assets — screenshots of the dashboard

Capture of the real dashboard, taken from the running receiver (`node video/capture_shots.mjs`).
Every frame is a genuine render of `dashboard/report.html`: the live ones come from
`server/data/events.ndjson`, and the eight-session ones carry the *synthetic dataset* banner
saying so. Nothing here is hand-drawn.

Full frames are **1920×1080** (drop straight on a 1080p timeline). Panels are element-clipped at
their natural size — scale them up to taste, or cut them in over a blurred background.

| File | What it shows | Where to put it in the video |
|---|---|---|
| `01-live-overview.png` | Live register: 4 sessions, 18 scans, students, timeline | ~44 s — "the laptop only records the scans" |
| `02-live-students-panel.png` | Student table: % attendance, days present, flags, status pill | with the overview, or ~2:12 for the attendance claim |
| `03-live-timeline-panel.png` | Session timeline with per-scan marks and start–end windows | ~57 s — when the architecture is on screen |
| `04-live-scanlog-panel.png` | Scan log: every real scan, newest first, timestamps + GRANTED/DENIED | ~1:19 — "the dashboard updates itself" |
| `05-sample-session1-watch30.png` | Session 1: 4 cards, WATCH 30 — restraint, not accusation | ~2:28 — the honest-limits beat |
| `06-sample-session3-review63.png` | Session 3: **REVIEW 63**, five cards in 0.95 s | ~1:36 — "this is the cheat" |
| `07-sample-session3-arithmetic.png` | Close insert: weights and points adding to 0.629 → 63 REVIEW | ~1:55 — the scoring slide |
| `08-sample-session5-high71.png` | Session 5: **HIGH 71**, same chain repeated | ~2:16 — "a repeat scores higher" |
| `09-sample-all-sessions.png` | Whole set: 8 sessions, 16 students, 82%, 5 flagged, 4 review+, 3 high | ~2:12 — the results summary |
| `10-sample-all-incidents.png` | All five flagged runs in one column: 80 PROBING, 71, 71, 63, 30 | ~2:20 — evidence one after another |
| `11-student-drawer.png` | Student drawer: day-by-day presence, their scans, eligibility | ~2:09 — "click any student" |

## Numbers these frames prove (they match `REPORT.md` / `CHEATSHEET.md`)

| Session | Score | Band | Why |
|---|---|---|---|
| session_01 | 30 | WATCH | 4 cards in 2.28 s — fast, but no pair under 0.5 s |
| session_03 | 63 | REVIEW | 5 cards in 0.95 s, all gaps under 0.5 s |
| session_05 | 71 | HIGH | same chain repeated, rigidity now pays |
| session_06 | 80 | HIGH | 0 cards, 5 rejected cards in 6 s — credential probing |
| session_08 | 71 | HIGH | chain seen twice before, crowd z-score 0.43 |

Eight sessions, 16 students, **82%** average, 5 flagged runs, 4 at review-or-above, 3 high.

> `analysis/state/model.json` is learned state. It had drifted from repeated `detect.py` runs, so
> session 3 was scoring 73/HIGH instead of the documented 63/REVIEW. It was reset and the payload
> regenerated, which is why these frames now agree with the report. The previous file is kept at
> `/tmp/model.json.bak`. **Run `detect.py` with `--no-learn`** from now on unless you mean to
> re-train.

## Recapturing

```bash
./start.sh                    # receiver must be serving 127.0.0.1:8080
node video/capture_shots.mjs  # rewrites every PNG above
```

The script drives the installed Chrome over the DevTools protocol — no npm packages, no browser
automation dependency. Screenshot states are listed in `SHOTS` at the top of the file; add an
entry to capture another panel.

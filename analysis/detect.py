#!/usr/bin/env python3
"""
Multi-signal proxy-attendance risk engine.

Reads the NDJSON event log written by the ESP32 firmware and groups suspicious
scans into incidents, each with a 0-100 risk score, a band, and human-readable
reasons. Baselines are learned from previous sessions, so the same behaviour is
judged differently for a student who normally arrives alone versus two friends
who walk in together every day.

Design notes (viva ammunition):

  * Physics beats statistics. A doorway passes roughly one person per 0.6 s, so
    two DIFFERENT cards read under 0.5 s apart cannot be two people walking
    through. That is near-certain evidence and carries the largest weight.
  * 0.5-1.2 s is the ambiguous zone: fast friends, or a stack tap. Here the
    learned companion baseline decides, which is what removes the false
    positive on people who always enter together.
  * Repetition of the SAME ORDERED chain across sessions is a stack signature:
    a wallet has a fixed card order, people do not.
  * Thresholds are on a weighted score, not a single hard rule, so one weak
    signal never raises an alarm on its own.

Usage:
  python3 detect.py data/*.ndjson --state state/model.json
  python3 detect.py --eval --state /tmp/eval-state.json
  python3 detect.py data/session_05.ndjson --min-band REVIEW
"""

import argparse
import csv
import glob
import json
import os
import statistics
from datetime import datetime

# ----------------------------------------------------------------- model knobs
GAP_PHYS = 0.50        # below this two different cards cannot be two people
GAP_FAST = 1.20        # upper edge of the ambiguous zone
MIN_RUN = 3            # a lone fast scan is normal; a run of 3+ is not
CTX_WINDOW = 5.0       # seconds of context when counting neighbours
PROBE_WINDOW = 15.0    # window for "several unregistered cards" probing
PROBE_MIN = 3

WEIGHTS = {
    "burst": 0.20,     # how many cards in the run
    "phys": 0.40,      # fraction of gaps below the physical limit
    "tight": 0.10,     # fraction of gaps in the ambiguous zone
    "ctx": 0.12,       # how unusual this many neighbours is FOR THIS STUDENT
    "rigid": 0.10,     # how often this exact ordered chain repeats
    "new": 0.05,       # cards never seen before
    "denied": 0.03,    # unregistered cards around the same moment
}
COMPANION_DISCOUNT = 0.55   # how much habitual pairs can cancel the ambiguity

BANDS = ((70, "HIGH"), (50, "REVIEW"), (30, "WATCH"), (0, "CLEAR"))
BAND_RANK = {"CLEAR": 0, "WATCH": 1, "REVIEW": 2, "HIGH": 3}


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def pct(x):
    return f"{round(x * 100)}%"


# ------------------------------------------------------------------ event load
def event_time(ev):
    if "t" in ev:
        try:
            return float(ev["t"])
        except (TypeError, ValueError):
            return None
    ts = str(ev.get("ts", ""))
    if ts.startswith("T+"):
        try:
            return float(ts[2:].rstrip("s"))
        except ValueError:
            return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(ts, fmt).timestamp()
        except ValueError:
            pass
    return None


def load_session(path):
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue          # torn line at the end of a power-cut log
            t = event_time(ev)
            if t is None:
                continue
            ev["t"] = t
            events.append(ev)
    events.sort(key=lambda e: e["t"])
    return events


def add_context(events):
    """How many distinct students were scanned in the few seconds before each."""
    for i, ev in enumerate(events):
        seen = set()
        for j in range(i - 1, -1, -1):
            if ev["t"] - events[j]["t"] > CTX_WINDOW:
                break
            if events[j].get("roll"):
                seen.add(events[j]["roll"])
        ev["ctx"] = len(seen)
    return events


def clock(t):
    return datetime.fromtimestamp(t).strftime("%H:%M:%S.%f")[:-3]


def stamp(t, ev=None):
    """Human-readable moment for an incident.

    Prefers the ISO timestamp actually logged by the device. Falls back to a
    clearly-labelled relative time when the board had no clock, so a real date
    is never invented for a log that never had one.
    """
    ts = str((ev or {}).get("ts", ""))
    if ts and not ts.startswith("T+"):
        return ts.replace("T", " ")
    if t > 946684800:            # plausible epoch, i.e. after the year 2000
        return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
    return f"T+{t:.0f}s (device had no clock)"


# -------------------------------------------------------------------- baseline
class Baseline:
    def __init__(self, data=None):
        data = data or {}
        self.students = data.get("students", {})   # roll -> {"ctx": [...], "sessions": n}
        self.pairs = data.get("pairs", {})         # "a|b" -> times adjacent-fast
        self.chains = data.get("chains", {})       # "a>b>c" -> times seen as a fast run
        self.sessions = data.get("sessions", 0)

    @classmethod
    def load(cls, path):
        if path and os.path.exists(path):
            with open(path) as f:
                return cls(json.load(f))
        return cls()

    def save(self, path):
        if not path:
            return
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.__dict__, f)

    # -- learned lookups -----------------------------------------------------
    def student_sessions(self, roll):
        return self.students.get(roll, {}).get("sessions", 0)

    def ctx_z(self, roll, ctx):
        """How many standard deviations above this student's usual crowd."""
        hist = self.students.get(roll, {}).get("ctx", [])
        if len(hist) < 3:
            med, mad = 1.0, 0.7          # cold-start prior: most arrivals are alone
        else:
            med = statistics.median(hist)
            mad = statistics.median([abs(h - med) for h in hist])
        z = (ctx - med) / (1.4826 * mad + 0.6)
        return clamp(z / 3.0)

    def rigidity(self, rolls):
        """How often this exact ordered chain has appeared as a fast run before."""
        if self.sessions == 0:
            return 0.0
        seen = self.chains.get(">".join(rolls), 0)
        return clamp(seen / max(2.0, self.sessions * 0.5))

    def habit(self, rolls):
        """Order-insensitive companionship: did these pairs always arrive together?"""
        scores = []
        for a, b in zip(rolls, rolls[1:]):
            key = "|".join(sorted((a, b)))
            n = self.pairs.get(key, 0)
            shared = min(self.student_sessions(a), self.student_sessions(b))
            if shared == 0:
                scores.append(0.0)
            else:
                scores.append(clamp(n / shared))
        return statistics.mean(scores) if scores else 0.0

    # -- learning ------------------------------------------------------------
    def learn(self, events):
        grants = [e for e in events if e.get("result") == "GRANTED" and e.get("roll")]
        for ev in grants:
            st = self.students.setdefault(ev["roll"], {"ctx": [], "sessions": 0})
            st["ctx"] = (st["ctx"] + [ev.get("ctx", 0)])[-40:]
            st["sessions"] += 1

        # Companionship is only learned from HUMANLY POSSIBLE gaps. Otherwise a
        # repeated stack tap would teach the model that those students always
        # arrive together and earn itself a discount.
        for a, b in zip(grants, grants[1:]):
            gap = b["t"] - a["t"]
            if GAP_PHYS <= gap < GAP_FAST and a["roll"] != b["roll"]:
                key = "|".join(sorted((a["roll"], b["roll"])))
                self.pairs[key] = self.pairs.get(key, 0) + 1

        for run in fast_runs(grants):
            if len(run) >= MIN_RUN:
                key = ">".join(e["roll"] for e in run)
                self.chains[key] = self.chains.get(key, 0) + 1

        self.sessions += 1


def fast_runs(grants):
    """Maximal sequences of grants whose consecutive gaps are under GAP_FAST."""
    out, i = [], 0
    while i < len(grants):
        j = i
        while j + 1 < len(grants) and grants[j + 1]["t"] - grants[j]["t"] < GAP_FAST:
            j += 1
        out.append(grants[i:j + 1])
        i = j + 1
    return out


# --------------------------------------------------------------------- scoring
def score_run(run, base, denials):
    rolls = [e["roll"] for e in run]
    gaps = [run[i]["t"] - run[i - 1]["t"] for i in range(1, len(run))]

    s_burst = clamp((len(run) - 2) / 3.0)
    s_phys = sum(1 for g in gaps if g < GAP_PHYS) / len(gaps)
    s_tight = sum(1 for g in gaps if GAP_PHYS <= g < GAP_FAST) / len(gaps)
    s_ctx = statistics.mean(base.ctx_z(e["roll"], e.get("ctx", 0)) for e in run)
    s_rigid = base.rigidity(rolls)
    s_new = statistics.mean(
        1.0 if base.student_sessions(r) == 0 else 0.0 for r in set(rolls))
    t0 = run[0]["t"]
    s_denied = 1.0 if any(0 <= d["t"] - t0 <= PROBE_WINDOW for d in denials) else 0.0

    habit = base.habit(rolls)

    chain_seen = base.chains.get(">".join(rolls), 0)
    fast_pairs = sum(1 for g in gaps if g < GAP_PHYS)
    tight_pairs = sum(1 for g in gaps if GAP_PHYS <= g < GAP_FAST)

    rows = [
        ("impossible-gap", "phys", s_phys,
         f"{fast_pairs}/{len(gaps)} gaps under {GAP_PHYS}s"),
        ("burst", "burst", s_burst, f"{len(run)} cards in {sum(gaps):.2f}s"),
        ("crowd-anomaly", "ctx", s_ctx, "vs this student's usual neighbours"),
        ("tight-gaps", "tight", s_tight,
         f"{tight_pairs}/{len(gaps)} gaps in {GAP_PHYS}-{GAP_FAST}s"),
        ("order-rigidity", "rigid", s_rigid,
         f"this exact chain seen {chain_seen}x before"),
        ("new-cards", "new", s_new, "share never seen in earlier sessions"),
        ("nearby-denials", "denied", s_denied, "unregistered cards in the same window"),
    ]

    breakdown = []
    base_score = 0.0
    for label, key, value, note in rows:
        points = WEIGHTS[key] * value
        base_score += points
        breakdown.append({"signal": label, "value": round(value, 3),
                          "weight": WEIGHTS[key], "points": round(points, 3),
                          "note": note})

    ambiguous = sum(b["points"] for b in breakdown
                    if b["signal"] in ("tight-gaps", "crowd-anomaly", "order-rigidity"))
    discount = COMPANION_DISCOUNT * habit * ambiguous
    raw = base_score - discount

    score = int(round(100 * clamp(raw)))
    band = next(name for floor, name in BANDS if score >= floor)

    math_line = " + ".join(f"{b['weight']:.2f}x{b['value']:.2f}" for b in breakdown)
    math_line = f"({math_line}) = {base_score:.3f}"
    if discount > 0:
        math_line += f" - {discount:.3f} companion discount = {raw:.3f}"
    math_line += f" -> {score}/100 {band}"

    reasons = []
    if s_phys > 0:
        reasons.append(f"impossible-gap {pct(s_phys)} of pairs under {GAP_PHYS}s")
    if len(run) >= MIN_RUN:
        reasons.append(f"burst {len(run)} cards in {gaps and sum(gaps):.1f}s")
    if s_rigid > 0.2:
        reasons.append(f"same-ordered-chain seen {base.chains.get('>'.join(rolls), 0)}x before")
    if s_ctx > 0.4:
        reasons.append(f"crowd-anomaly z-score {s_ctx:.2f} vs this student's history")
    if s_new > 0:
        reasons.append(f"{pct(s_new)} of cards never seen before")
    if s_denied:
        reasons.append("unregistered cards scanned nearby")
    if habit > 0.35:
        reasons.append(f"habitual companions {pct(habit)} - discounted")

    return {
        "score": score, "band": band, "start": run[0]["t"],
        "end": run[-1]["t"], "cards": len(run),
        "rolls": rolls, "events": run, "reasons": reasons,
        "habit": habit, "gaps": gaps,
        "breakdown": breakdown, "base_score": round(base_score, 3),
        "discount": round(discount, 3), "math": math_line,
    }


def detect(session, base):
    grants = [e for e in session if e.get("result") == "GRANTED" and e.get("roll")]
    denials = [e for e in session if e.get("result") == "DENIED"]
    incidents = []

    for run in fast_runs(grants):
        if len(run) >= MIN_RUN:
            incidents.append(score_run(run, base, denials))

    if len(denials) >= PROBE_MIN:
        span = denials[-1]["t"] - denials[0]["t"]
        if span <= PROBE_WINDOW:
            score = int(round(100 * clamp(0.55 + 0.05 * len(denials))))
            band = next(name for floor, name in BANDS if score >= floor)
            incidents.append({
                "score": score,
                "band": band, "start": denials[0]["t"], "end": denials[-1]["t"],
                "cards": 0, "rolls": [], "events": denials, "gaps": [],
                "habit": 0.0, "breakdown": [], "base_score": round(score / 100, 3),
                "discount": 0.0,
                "math": f"0.55 + 0.05x{len(denials)} denies = {score / 100:.2f}"
                        f" -> {score}/100 {band}",
                "reasons": [f"{len(denials)} unregistered cards rejected in {span:.0f}s "
                            "- credential probing"],
                "kind": "PROBING",
            })
    incidents.sort(key=lambda i: i["score"], reverse=True)
    return incidents


# ---------------------------------------------------------------------- output
def print_session(path, session, incidents, min_band, explain=False):
    students = len({e["roll"] for e in session if e.get("roll")})
    print(f"\n== {os.path.basename(path)}  {len(session)} events  {students} students")
    shown = [i for i in incidents if BAND_RANK[i["band"]] >= BAND_RANK[min_band]]
    if not shown:
        print("   no incidents in band " + min_band)
        return
    for n, inc in enumerate(shown, 1):
        tag = inc.get("kind", "STACK-TAP")
        print(f"   INC-{n}  {inc['score']:3d}/100 {inc['band']:<6} {tag:<10} "
              f"{clock(inc['start'])} -> {clock(inc['end'])}")
        prev = None
        for ev in inc["events"][:8]:
            label = ev.get("roll") or "(unknown card)"
            gap = "-" if prev is None else f"{ev['t'] - prev:.2f}s"
            print(f"      {clock(ev['t'])}  {label:<7} {ev.get('name',''):<14} gap {gap}")
            prev = ev["t"]
        for r in inc["reasons"]:
            print(f"      - {r}")
        if explain:
            print("      how the score was built")
            for b in inc.get("breakdown", []):
                print(f"        {b['signal']:<16}{b['value']:>5.2f} x {b['weight']:.2f}"
                      f" = {b['points']:>6.3f}   {b['note']}")
            if inc.get("breakdown"):
                print(f"        {'raw total':<16}{'':>5}   {'':>5}   {inc['base_score']:>6.3f}")
                if inc.get("discount"):
                    print(f"        {'companion':<16}{'':>5}   {'':>5}  -{inc['discount']:>6.3f}"
                          f"   learned habitual pair, cancels part of the ambiguity")
                print(f"        {'final':<16}{'':>5}   {'':>5}   {inc['score']:>5}/100 {inc['band']}")
                print(f"        {inc.get('math','')}")
            print(f"        when              {stamp(inc['start'], inc['events'][0])}"
                  f"   duration {inc['end'] - inc['start']:.2f}s")


def evaluate(data_dir, base):
    labels_path = os.path.join(data_dir, "labels.json")
    if not os.path.exists(labels_path):
        print("no labels.json - run simulate.py first")
        return
    with open(labels_path) as f:
        labels = json.load(f)

    tp = fp = fn = tn = 0
    print(f"{'session':<20}{'truth':<9}{'incidents':<14}verdict")
    for entry in labels["sessions"]:
        path = os.path.join(data_dir, entry["file"])
        if not os.path.exists(path):
            continue
        session = add_context(load_session(path))
        incidents = detect(session, base)
        base.learn(session)             # learn AFTER scoring: no leakage

        strong = [i for i in incidents
                  if BAND_RANK[i["band"]] >= BAND_RANK["REVIEW"]]
        truth_proxy = bool(entry["proxy"])
        truth_probe = entry.get("probing", False)
        caught = bool(strong)

        if truth_proxy or truth_probe:
            if caught:
                tp += 1
            else:
                fn += 1
        else:
            if caught:
                fp += 1
            else:
                tn += 1

        top = f"{strong[0]['score']}/100 {strong[0]['band']}" if strong else "-"
        verdict = "caught" if caught and (truth_proxy or truth_probe) else \
                  ("FALSE ALARM" if caught else "clean")
        print(f"{entry['file']:<20}{entry['kind']:<9}{top:<14}{verdict}")

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    print(f"\ncaught {tp}/{tp + fn} attack sessions   false alarms {fp}/{fp + tn} clean sessions")
    print(f"precision {precision:.2f}   recall {recall:.2f}")


def build_payload(records):
    """Aggregate scored sessions into the dashboard payload (shared by the
    static exporter here and the live server in server/server.py)."""
    sessions, incidents_out = [], []
    per_student = {}
    n_sessions = len(records)

    for idx, (path, events, incidents) in enumerate(records):
        name = os.path.splitext(os.path.basename(path))[0]
        grants = [e for e in events if e.get("result") == "GRANTED" and e.get("roll")]
        for e in grants:
            st = per_student.setdefault(e["roll"], {"name": e.get("name", ""),
                                                    "present": set(), "flags": 0})
            st["present"].add(idx)

        flagged = set()
        for inc in incidents:
            if BAND_RANK[inc["band"]] >= BAND_RANK["REVIEW"]:
                flagged |= set(inc["rolls"])
        for r in flagged:
            if r in per_student:
                per_student[r]["flags"] += 1

        t0 = events[0]["t"] if events else 0.0
        span = max(1e-6, (events[-1]["t"] - t0) if events else 1.0)
        timeline = [{"x": round(100 * (e["t"] - t0) / span, 2),
                     "roll": e.get("roll") or "",
                     "result": e.get("result", ""),
                     "ts": stamp(e["t"], e),          # wall-clock, or "T+3s" if the board had no clock
                     "src": e.get("src", ""),
                     "flag": e.get("roll") in flagged} for e in events]

        first_stamp = stamp(t0, events[0]) if events else ""
        sessions.append({"name": name, "events": len(events),
                         "students": len(grants), "incidents": len(incidents),
                         # a clockless session has no date: don't put "T+59s" in the date slot
                         "date": first_stamp.split(" ")[0] if first_stamp[:4].isdigit() else "",
                         "flagged": bool(flagged), "timeline": timeline})

        for inc in incidents:
            if BAND_RANK[inc["band"]] < BAND_RANK["WATCH"]:
                continue          # not an incident, just a fast-looking run
            incidents_out.append({
                "session": name, "score": inc["score"], "band": inc["band"],
                "kind": inc.get("kind", "STACK-TAP"),
                "when": stamp(inc["start"], inc["events"][0]),
                "breakdown": inc.get("breakdown", []),
                "base_score": inc.get("base_score", 0.0),
                "discount": inc.get("discount", 0.0),
                "math": inc.get("math", ""),
                "time": clock(inc["start"]),
                "duration": round(inc["end"] - inc["start"], 2),
                "cards": inc["cards"], "rolls": inc["rolls"],
                "reasons": inc["reasons"],
                "events": [{"roll": e.get("roll") or "(unknown)",
                            "name": e.get("name", ""),
                            "time": clock(e["t"])} for e in inc["events"]],
            })

    students = []
    for roll, st in sorted(per_student.items()):
        present = len(st["present"])
        pct = round(100 * present / max(1, n_sessions))
        students.append({"roll": roll, "name": st["name"], "present": present,
                         "total": n_sessions, "percent": pct,
                         "flags": st["flags"], "eligible": pct >= 75})

    return {"generated": datetime.now().strftime("%d %b %Y, %H:%M"),
            "sessions": sessions, "students": students,
            "incidents": incidents_out}


def write_dashboard(out_path, records, template_path):
    """Emit a self-contained HTML dashboard plus the raw payload as JSON."""
    payload = build_payload(records)

    with open(template_path) as f:
        html = f.read()
    html = html.replace("__DATA_JSON__", json.dumps(payload))

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        f.write(html)

    json_path = os.path.splitext(out_path)[0] + ".json"
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"\ndashboard: {out_path} ({len(payload['students'])} students, "
          f"{len(payload['incidents'])} incidents)")
    print(f"payload:   {json_path}")


def write_csv(prefix, records):
    """Audit tables for the report appendix."""
    payload = build_payload(records)

    incidents_path = prefix + "_incidents.csv"
    with open(incidents_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["session", "when", "score", "band", "kind", "cards",
                    "students", "reasons"])
        for i in payload["incidents"]:
            w.writerow([i["session"], i["when"], i["score"], i["band"],
                        i["kind"], i["cards"], " ".join(i["rolls"]),
                        " | ".join(i["reasons"])])

    students_path = prefix + "_students.csv"
    with open(students_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["roll", "name", "present", "sessions", "percent",
                    "eligible", "flags"])
        for s in payload["students"]:
            w.writerow([s["roll"], s["name"], s["present"], s["total"],
                        s["percent"], "yes" if s["eligible"] else "no",
                        s["flags"]])

    print(f"csv: {incidents_path}, {students_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", help="NDJSON session logs")
    ap.add_argument("--state", default="state/model.json", help="baseline file")
    ap.add_argument("--eval", action="store_true", help="score labelled data/simulate output")
    ap.add_argument("--data", default="data", help="folder with labels.json for --eval")
    ap.add_argument("--min-band", default="WATCH", choices=list(BAND_RANK))
    ap.add_argument("--no-learn", action="store_true")
    ap.add_argument("--dashboard", metavar="OUT.html",
                    help="also write a standalone monitoring dashboard")
    ap.add_argument("--template", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "dashboard_template.html"))
    ap.add_argument("--explain", action="store_true",
                    help="print the full arithmetic behind every score")
    ap.add_argument("--csv", metavar="PREFIX",
                    help="write PREFIX_incidents.csv and PREFIX_students.csv")
    args = ap.parse_args()

    base = Baseline.load(args.state)

    if args.eval:
        evaluate(args.data, base)
        return

    files = args.files or sorted(glob.glob(os.path.join(args.data, "*.ndjson")))
    if not files:
        ap.error("no session files given")

    records = []
    for path in files:
        session = add_context(load_session(path))
        incidents = detect(session, base)
        print_session(path, session, incidents, args.min_band, args.explain)
        records.append((path, session, incidents))
        if not args.no_learn:
            base.learn(session)

    if args.dashboard:
        write_dashboard(args.dashboard, records, args.template)

    if args.csv:
        write_csv(args.csv, records)

    if not args.no_learn:
        base.save(args.state)
        print(f"\nbaseline saved to {args.state} "
              f"({base.sessions} sessions, {len(base.students)} students, "
              f"{len(base.pairs)} pairs, {len(base.chains)} chains)")


if __name__ == "__main__":
    main()

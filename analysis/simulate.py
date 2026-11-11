#!/usr/bin/env python3
"""
Synthetic session generator for the proxy-attendance risk engine.

Produces NDJSON event logs in exactly the shape the ESP32 firmware writes, plus
a labels.json that says which students were actually scanned by someone else.
That lets us *measure* the detector instead of guessing.

Scenarios generated:
  clean       normal arrivals, including a pair of friends who habitually
              walk in together (the false-positive trap)
  proxy       one person taps 4-6 other students' cards in a fast stack
  probing     someone tries several unregistered cards in a row
"""

import argparse
import json
import math
import os
import random
from datetime import datetime, timedelta, timezone

NAMES = ["Aisha", "Rohit", "Sara", "Imran", "Neha", "Vikram", "Priya", "Arjun",
         "Meera", "Kabir", "Ananya", "Rahul", "Zara", "Dev", "Isha", "Manav",
         "Tara", "Yash", "Kiran", "Riya"]

BASE = datetime(2026, 11, 7, 10, 0, 0, tzinfo=timezone.utc)


def build_cohort(n):
    return [{"roll": f"CS-{i + 1:02d}", "name": NAMES[i]} for i in range(n)]


def uid_for(roll):
    i = int(roll.split("-")[1])
    return " ".join(f"{(i * 37 + j * 11) & 0xFF:02X}" for j in range(4))


def mk(student, t, result="GRANTED", attendance="PRESENT", simulated=False):
    stamp = BASE + timedelta(seconds=t)
    return {
        "uid": uid_for(student["roll"]) if student else "DE AD BE EF",
        "name": student["name"] if student else "",
        "roll": student["roll"] if student else "",
        "result": result,
        "attendance": attendance,
        "suspect": False,
        "simulated": simulated,
        "t": round(t, 2),
        "ts": stamp.strftime("%Y-%m-%dT%H:%M:%S"),
        "src": "ntp",
    }


def clean_session(cohort, rng, start, buddies, trio):
    """Normal walking-in. No cheating at all -- but it does include a group of
    three friends who always arrive together, which is the hardest legitimate
    case for the detector."""
    events = []
    order = cohort[:]
    rng.shuffle(order)
    order = order[: rng.randint(int(len(cohort) * 0.7), len(cohort))]

    t = start + 3.0
    remaining = order[:]
    while remaining:
        s = remaining.pop(0)

        # three friends always walk in together, in a different order each day
        if s["roll"] in trio:
            group = [s] + [r for r in remaining if r["roll"] in trio]
            if len(group) == 3:
                for g in group[1:]:
                    remaining.remove(g)
                rng.shuffle(group)
                for g in group:
                    t += rng.uniform(0.55, 0.95)
                    events.append(mk(g, t))
                t += rng.uniform(1.5, 3.0)
                continue

        # a pair of friends who always arrive together
        mate = buddies.get(s["roll"])
        if mate and remaining and remaining[0]["roll"] == mate:
            pair = [s, remaining.pop(0)]
            if rng.random() < 0.5:
                pair.reverse()
            for p in pair:
                t += rng.uniform(0.6, 1.4)
                events.append(mk(p, t))
            t += rng.uniform(1.5, 3.0)
            continue

        t += max(0.8, rng.lognormvariate(math.log(3.2), 0.5))
        events.append(mk(s, t))
    return events


def proxy_attack(collector, ring, rng, start):
    """A collector walks up, taps their own card, then the same ring of
    classmates' cards in wallet order -- the recurring signature."""
    out = [mk(collector, start)]
    t = start
    for s in ring:
        t += rng.uniform(0.12, 0.34)
        out.append(mk(s, t))
    return out, [s["roll"] for s in ring]


def make_session(cohort, rng, start, kind, buddies, trio, ring, attack_size):
    meta = {"kind": kind, "proxy": [], "probing": False}
    events = clean_session(cohort, rng, start, buddies, trio)

    if kind == "proxy":
        collector = ring[0]
        victims = ring[1:1 + attack_size]
        # start the burst well clear of the normal arrival stream
        gap_before = max(e["t"] for e in events if e["t"] < start + 38)
        attack, proxy_rolls = proxy_attack(collector, victims, rng, gap_before + 6.0)
        events = [e for e in events if e["t"] < start + 38] + attack
        meta["proxy"] = proxy_rolls

    if kind == "probing":
        t = max(e["t"] for e in events) + 8.0
        for _ in range(5):
            t += rng.uniform(0.8, 2.0)
            events.append(mk(None, t, result="DENIED", attendance="NOT_RECORDED"))
        meta["probing"] = True

    events.sort(key=lambda e: e["t"])
    return events, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    ap.add_argument("--sessions", type=int, default=6)
    ap.add_argument("--cohort", type=int, default=16)
    ap.add_argument("--attack-size", type=int, default=5)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    cohort = build_cohort(args.cohort)

    # a pair of friends who walk in together every single session
    buddies = {cohort[3]["roll"]: cohort[7]["roll"],
               cohort[7]["roll"]: cohort[3]["roll"]}
    # ... and three friends who always arrive together
    trio = {cohort[12]["roll"], cohort[13]["roll"], cohort[14]["roll"]}
    # the proxy ring: one collector, four classmates whose cards get tapped
    ring = [cohort[0], cohort[2], cohort[5], cohort[8], cohort[10]]

    plan = ["clean", "clean", "proxy", "clean", "proxy", "probing", "clean", "proxy"]
    # sessions with a friend group are the false-positive traps: the plan's
    # "clean" sessions contain the pair and the trio.
    os.makedirs(args.out, exist_ok=True)

    labels = {"sessions": []}
    for i in range(args.sessions):
        kind = plan[i % len(plan)]
        events, meta = make_session(cohort, rng, i * 3600.0, kind, buddies,
                                    trio, ring, args.attack_size)
        name = f"session_{i + 1:02d}.ndjson"
        path = os.path.join(args.out, name)
        with open(path, "w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
        labels["sessions"].append({"file": name, "kind": kind,
                                   "proxy": meta["proxy"],
                                   "probing": meta["probing"]})
        print(f"{path:28s} {kind:8s} {len(events):3d} events "
              f"proxy={','.join(meta['proxy']) or '-'}")

    with open(os.path.join(args.out, "labels.json"), "w") as f:
        json.dump(labels, f, indent=2)
    print(f"\n{args.sessions} sessions written to {args.out}/")


if __name__ == "__main__":
    main()

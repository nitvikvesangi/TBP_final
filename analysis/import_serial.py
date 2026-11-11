#!/usr/bin/env python3
"""
Turn a raw Serial Monitor capture into clean NDJSON for the analysis.

The board prints a lot that is not an event: boot lines, the help text, echoed
commands, `dump` markers, and every record twice (once live, once from `dump`).
This pulls out the JSON event lines, drops duplicates, and tells you what it
threw away.

    python3 import_serial.py capture.txt -o data/session_real_01.ndjson
    python3 import_serial.py - -o data/session_real_01.ndjson < capture.txt
    python3 import_serial.py capture.txt --drop-simulated

Duplicates are keyed on uid + timestamp + result + attendance, so a record that
appears both on screen and in a `dump` block is kept exactly once.
"""

import argparse
import json
import sys

REQUIRED = ("uid", "result")


def parse_capture(stream):
    events, skipped, dupes = [], 0, 0
    seen = set()
    for raw in stream:
        line = raw.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if not isinstance(ev, dict) or any(k not in ev for k in REQUIRED):
            skipped += 1
            continue
        key = (ev.get("uid"), ev.get("ts"), ev.get("result"), ev.get("attendance"))
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        events.append(ev)
    return events, skipped, dupes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("capture", help="serial capture file, or - for stdin")
    ap.add_argument("-o", "--out", required=True, help="output .ndjson path")
    ap.add_argument("--drop-simulated", action="store_true",
                    help="exclude events produced with the sim command")
    args = ap.parse_args()

    if args.capture == "-":
        events, skipped, dupes = parse_capture(sys.stdin)
    else:
        with open(args.capture, errors="replace") as f:
            events, skipped, dupes = parse_capture(f)

    if args.drop_simulated:
        before = len(events)
        events = [e for e in events if not e.get("simulated")]
        print(f"dropped {before - len(events)} simulated events")

    if not events:
        sys.exit("no events found - is this really a Serial Monitor capture?")

    grants = sum(1 for e in events if e.get("result") == "GRANTED")
    denials = len(events) - grants

    with open(args.out, "w") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")

    print(f"wrote {len(events)} events -> {args.out}")
    print(f"  granted {grants}   denied {denials}   "
          f"duplicates removed {dupes}   unparsable {skipped}")


if __name__ == "__main__":
    main()

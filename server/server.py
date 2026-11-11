#!/usr/bin/env python3
"""
Local receiver + live dashboard for the RFID attendance prototype.

Runs on your laptop, no dependencies, no cloud account:

    python3 server/server.py                 # open mode
    python3 server/server.py --token S3cret  # same value as CLOUD_TOKEN

Then put the printed URL into CLOUD_URL in the sketch and re-upload.

  POST /api/scan      device uploads one JSON event  -> data/events.ndjson
  GET  /api/summary   attendance % + scored incidents (reuses detect.py)
  GET  /              the dashboard, live
  GET  /health        {"ok":true}

Nothing is deleted: events are appended, so the file is your audit trail.
The shared token stops any other device on the hotspot posting fake records.
"""

import argparse
import json
import os
import socket
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "analysis"))

import detect  # noqa: E402  (import needs the path above)

DATA_DIR = os.path.join(HERE, "data")
EVENTS = os.path.join(DATA_DIR, "events.ndjson")
MODEL = os.path.join(ROOT, "analysis", "state", "model.json")
DASHBOARD = os.path.join(ROOT, "dashboard", "report.html")

_write_lock = threading.Lock()


def lan_ip():
    """Best-effort LAN address of this laptop (no traffic is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def empty_payload():
    return {"generated": datetime.now().strftime("%d %b %Y, %H:%M"),
            "sessions": [], "students": [], "incidents": []}


def summarize():
    """Group the event log by day and score each day as one session."""
    if not os.path.exists(EVENTS):
        return empty_payload()

    events = detect.load_session(EVENTS)
    if not events:
        return empty_payload()

    groups = {}
    for ev in events:
        day = datetime.fromtimestamp(ev["t"]).strftime("%d %b %Y")
        groups.setdefault(day, []).append(ev)

    base = detect.Baseline.load(MODEL)
    records = []
    ordered = sorted(groups, key=lambda d: min(e["t"] for e in groups[d]))
    for i, day in enumerate(ordered):
        session = detect.add_context(sorted(groups[day], key=lambda e: e["t"]))
        records.append((f"session_{i + 1:02d}", session, detect.detect(session, base)))
    return detect.build_payload(records)


class Handler(BaseHTTPRequestHandler):
    token = ""
    server_version = "RFIDAttendance/1.0"

    def log_message(self, fmt, *args):
        sys.stdout.write("  %s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/api/scan":
            return self._send(404, '{"error":"not found"}')

        if Handler.token and self.headers.get("X-Device-Token", "") != Handler.token:
            print("  ! rejected upload: bad or missing token")
            return self._send(401, '{"error":"bad token"}')

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 8192:
            return self._send(400, '{"error":"bad length"}')

        raw = self.rfile.read(length)
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return self._send(400, '{"error":"bad json"}')

        if "uid" not in event or "result" not in event:
            return self._send(400, '{"error":"missing uid or result"}')

        event["received_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        os.makedirs(DATA_DIR, exist_ok=True)
        with _write_lock:
            with open(EVENTS, "a") as f:
                f.write(json.dumps(event) + "\n")

        print(f"  + {event.get('ts', '?')}  {str(event.get('roll') or event['uid']):<18}"
              f" {event['result']}")
        return self._send(201, '{"ok":true}')

    def do_GET(self):
        if self.path.startswith("/api/summary"):
            return self._send(200, json.dumps(summarize()))

        if self.path in ("/", "/index.html"):
            if os.path.exists(DASHBOARD):
                with open(DASHBOARD, "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            return self._send(
                200,
                "<!doctype html><meta charset=utf-8>"
                "<body style='font:16px sans-serif;padding:40px;background:#0f172a;color:#e6edf7'>"
                "<h1>Dashboard not generated yet</h1>"
                "<p>Run: <code>python3 analysis/detect.py --dashboard dashboard/report.html"
                "</code></p><p>The API is already live at <code>/api/summary</code>.</p>",
                "text/html; charset=utf-8")

        if self.path == "/health":
            return self._send(200, '{"ok":true}')

        return self._send(404, '{"error":"not found"}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--token", default="",
                    help="shared secret; must match CLOUD_TOKEN in the sketch")
    args = ap.parse_args()

    Handler.token = args.token
    os.makedirs(DATA_DIR, exist_ok=True)

    ip = lan_ip()
    print("\nRFID attendance receiver")
    print(f"  upload URL : http://{ip}:{args.port}/api/scan")
    print(f"  dashboard  : http://{ip}:{args.port}/")
    print(f"  token      : {args.token or '(none - open)'}")
    print(f"  events file: {EVENTS}")
    print("\nPaste the upload URL into CLOUD_URL in the sketch, then upload it.\n")

    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()

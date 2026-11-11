#!/usr/bin/env python3
"""Cut the final silent (~3 min) project video.

Inputs, all already in this repo:
  - slides:        video/slides.html, rendered by headless Chrome (with ?clean=1)
  - dashboard:     video/shots/*.png (node video/capture_shots.mjs)
  - hardware:      the two "WhatsApp Video ..." clips in the project root

Every source is normalised to 1920x1080 / 30 fps on the paper background and gets
a burned-in caption. Captions are rendered as transparent PNGs by Chrome and
composited with ffmpeg's overlay filter, because this ffmpeg build has no
libfreetype (no drawtext). There is no audio track in the output.

    python3 video/build_final.py
    python3 video/build_final.py --out /tmp/cut.mp4
"""

import argparse
import os
import shutil
import subprocess
import sys
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
SLIDES = os.path.join(HERE, "slides.html")
CAPTIONS = os.path.join(HERE, "caption_card.html")
SHOTS = os.path.join(HERE, "shots")
WORK = os.path.join(HERE, "build_final")
OUT = os.path.join(HERE, "final.mp4")

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
W, H = 1920, 1080
CAP_H = 160              # height of the transparent caption strip
PAPER = "0xf6f2e9"       # same sheet colour as the slides

# (kind, source, seconds, caption)
#   slide <n>   - slide n of slides.html
#   shot  <id>  - video/shots/<id>.png
#   clip  <p>   - a video file (audio dropped); seconds = how much to use
TIMELINE = [
    ("slide", 1,  8,  "RFID smart attendance + door access"),
    ("slide", 2,  14, "The problem: one person, five friends' cards"),
    ("slide", 4,  12, "Components"),
    ("slide", 5,  11, "Software"),
    ("slide", 6,  15, "How it fits together"),
    ("slide", 7,  12, "One tap, four steps"),
    ("slide", 8,  14, "A real queue vs a stack of cards"),
    ("slide", 9,  14, "Scoring a run, 0 to 100"),

    ("shot", "06-sample-session3-review63",   5, "Session 3 - five cards in 0.95 s: REVIEW 63"),
    ("shot", "07-sample-session3-arithmetic", 5, "The arithmetic, printed on screen"),
    ("shot", "08-sample-session5-high71",     5, "Session 5 - same chain repeated: HIGH 71"),
    ("shot", "09-sample-all-sessions",        5, "8 sessions - 82% - 5 flagged runs"),

    ("shot", "01-live-overview",       5, "The live register, fed by the board"),
    ("shot", "04-live-scanlog-panel",  5, "Every scan, timestamped by the board"),

    ("clip", "WhatsApp Video 2026-11-11 at 22.24.24.mp4", 4.2, "Hardware - the card held at the reader"),
    ("clip", "WhatsApp Video 2026-11-11 at 22.24.28.mp4", 4.6, "Hardware - breadboard, reader and servo"),
    ("shot", "12-same-card-scans", 4, "Same card: rejected at 22:21, accepted at 22:22"),
    ("shot", "13-same-card-denied", 4, "Before registration - DENIED, the latch never moves"),
    ("shot", "14-same-card-granted", 4, "After registration - GRANTED, presence marked"),

    ("slide", 11, 12, "Results"),
    ("slide", 12, 10, "Limits, and what comes next"),
    ("slide", 13, 5,  "Thank you"),
]


def run(cmd, capture=False):
    return subprocess.run(cmd, check=True,
                          stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                          stderr=subprocess.PIPE, text=True)


def die(msg):
    print(f"  ! {msg}", file=sys.stderr)
    sys.exit(1)


def probe(path):
    p = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path], capture=True)
    return float(p.stdout.strip())


def chrome_shot(url, out, w, h, transparent=False):
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
           "--force-device-scale-factor=1", f"--window-size={w},{h}",
           "--no-first-run", "--no-default-browser-check", "--disable-extensions",
           f"--user-data-dir={os.path.join(WORK, 'chrome')}",
           "--virtual-time-budget=1500"]
    if transparent:
        cmd.append("--default-background-color=00000000")
    cmd += [f"--screenshot={out}", url]
    run(cmd)
    if not os.path.exists(out):
        die(f"nothing rendered for {url}")
    return out


def slide_png(n, out):
    return chrome_shot(f"file://{SLIDES}?clean=1#{n}", out, W, H)


def caption_png(text, out):
    return chrome_shot(f"file://{CAPTIONS}?text={quote(text)}", out, W, CAP_H, transparent=True)


def segment(kind, src, secs, caption, out, idx):
    cap = caption_png(caption, os.path.join(WORK, f"cap{idx:02d}.png"))
    chain = []
    if kind == "slide":
        img = slide_png(src, os.path.join(WORK, f"slide{src:02d}.png"))
        chain = [f"[0:v]scale={W}:{H}"]
        base = ["-loop", "1", "-i", img]
    elif kind == "shot":
        img = os.path.join(SHOTS, src + ".png")
        if not os.path.exists(img):
            die(f"missing shot {img} - run: node video/capture_shots.mjs")
        # panels are smaller than the frame: fit them, then sit them on paper
        chain = [f"[0:v]scale=1600:800:force_original_aspect_ratio=decrease",
                 f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={PAPER}"]
        base = ["-loop", "1", "-i", img]
    else:
        path = os.path.join(PROJ, src)
        if not os.path.exists(path):
            die(f"missing clip {path}")
        chain = [f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease",
                 f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x101010"]
        base = ["-i", path]

    graph = (",".join(chain) + ",fps=30,setsar=1[bg];"
             f"[1:v]scale={W}:{CAP_H}[cap];"
             f"[bg][cap]overlay=0:H-{CAP_H}:format=auto[v]")

    cmd = ["ffmpeg", "-y"] + base + ["-loop", "1", "-i", cap,
           "-t", f"{secs:.2f}", "-filter_complex", graph, "-map", "[v]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-pix_fmt", "yuv420p", "-r", "30", "-an", out]
    run(cmd)
    return probe(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    if not os.path.exists(CHROME):
        die("Google Chrome not found")
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            die(f"{tool} not found on PATH")
    os.makedirs(WORK, exist_ok=True)

    segs, total = [], 0.0
    for i, (kind, src, secs, caption) in enumerate(TIMELINE, start=1):
        out = os.path.join(WORK, f"seg{i:02d}.mp4")
        total += segment(kind, src, secs, caption, out, i)
        segs.append(out)
        print(f"  {i:02d} {kind:5} {str(src)[:44]:44} {secs:5.1f}s  {caption[:44]}")

    listfile = os.path.join(WORK, "concat.txt")
    with open(listfile, "w") as f:
        for s in segs:
            f.write(f"file '{s}'\n")

    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
         "-c", "copy", "-movflags", "+faststart", args.out])

    mins, secs = divmod(round(total), 60)
    mb = os.path.getsize(args.out) / 1_048_576
    print(f"\n  wrote {args.out}")
    print(f"  {mins}m {secs:02d}s · {W}x{H} · 30 fps · silent · {mb:.1f} MB · {len(segs)} segments")


if __name__ == "__main__":
    main()

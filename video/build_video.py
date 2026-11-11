#!/usr/bin/env python3
"""Build video/explainer.mp4 — a short, plain-language explainer.

Each entry in NARRATION pairs a slide from video/slides.html with a spoken line.
The slide is screenshotted with headless Chrome, narrated with macOS `say`, and
the pairs are cut together by ffmpeg. The result is capped at TARGET seconds
(default 180) by a uniform, pitch-preserving tempo adjustment, so the video is
always "about three minutes" no matter how the voice reads the text.

    python3 video/build_video.py
    VOICE=Veena RATE=150 python3 video/build_video.py
    TARGET=200 python3 video/build_video.py

Requires: Google Chrome, ffmpeg/ffprobe on PATH, macOS `say`.
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SLIDES = os.path.join(HERE, "slides.html")
WORK = os.path.join(HERE, "build")
OUT = os.path.join(HERE, "explainer.mp4")

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
VOICE = os.environ.get("VOICE", "Aman")        # en_IN voice that ships with macOS
RATE = int(os.environ.get("RATE", "160"))      # words per minute: slower reads as friendlier
TARGET = float(os.environ.get("TARGET", "180"))
PAD = 0.5                                      # seconds of air after each line
W, H = 1920, 1080

# (slide number in slides.html, spoken line)
#
# Written to be understood once, out loud, by someone who has never seen the
# project: short sentences, contractions, one idea per slide. The pauses are
# `say` silence commands - they are what stop it sounding like a document read
# aloud.
NARRATION = [
    (1, "This is our RFID attendance and door project. "
        "One tap should open the door and mark you present [[slnc 350]] and the system "
        "should notice when someone taps cards for their friends."),

    (2, "Right now, attendance means calling out names, which eats into class time. "
        "A card reader fixes the paperwork, but not the cheating. "
        "[[slnc 300]] A card only proves that a card was scanned. "
        "Nothing stops one person carrying five friends' cards and tapping them one by one."),

    (4, "The build is simple. The ESP32 does the thinking. "
        "The MFRC522 reader reads the card [[slnc 250]] and it needs three point three volts, "
        "because five volts destroys it. "
        "A small servo works the door latch, and two LEDs just say yes or no."),

    (5, "The board runs one Arduino program, and it keeps the list of allowed cards in its own "
        "memory. [[slnc 300]] So it still works with no laptop and no internet. "
        "The laptop only records the scans, and scores them."),

    (6, "Here's the flow. The card gets read, the ESP32 checks the list, and decides on the spot: "
        "green light and a latch nudge, or red light and nothing. "
        "[[slnc 350]] That decision never leaves the board. "
        "The scan also becomes a time stamped record, and when Wi-Fi is there it goes to the "
        "laptop. If it isn't, the record waits in memory and uploads later."),

    (7, "So one tap, four steps. Read the card. Is it on the list? "
        "No, red light, the door stays shut, and the attempt is still logged. "
        "[[slnc 250]] Yes, green light, the latch moves, and you're marked present. "
        "Tap the same card again and the door still opens, but you're not counted twice."),

    (8, "Now the clever part. Picture a real queue. "
        "One person every two or three seconds, because that's how fast you can walk through a "
        "door. [[slnc 300]] Now picture a hand fanning five cards. "
        "About a fifth of a second between each one. "
        "[[slnc 300]] A hand can move that fast. Two people cannot. "
        "That timing difference is the whole idea."),

    (9, "So the system times the taps, and gives each suspicious run a score out of a hundred. "
        "Cards too close together, too many too quickly, an unusual group of people, the same "
        "sequence coming back [[slnc 250]] all push the score up. "
        "And then it just flags it. A human decides."),

    (11, "On real hardware it works. A tap opens the door, and the dashboard updates itself in "
         "about two seconds, no refresh. "
         "[[slnc 300]] On eight test sessions it caught all four fake runs, and raised no false "
         "alarms. And the second time someone repeats a cheat, it scores higher."),

    (12, "Two honest limits. A cloned card carries the same ID, so you'd need stronger cards to "
         "stop that. [[slnc 250]] And one door can't prove travel time, so a slow, patient cheat "
         "looks normal. A second reader at a second door would fix it."),

    (13, "That's the project. One tap, two decisions [[slnc 250]] can this card come in, "
         "and is this attendance real? Thank you."),
]


def run(cmd, capture=False):
    return subprocess.run(cmd, check=True,
                          stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                          stderr=subprocess.PIPE,
                          text=True)


def die(msg):
    print(f"  ! {msg}", file=sys.stderr)
    sys.exit(1)


def check_tools():
    if not os.path.exists(CHROME):
        die("Google Chrome not found - install it, or edit CHROME in this file")
    for tool in ("ffmpeg", "ffprobe", "say"):
        if not shutil.which(tool):
            die(f"{tool} not found on PATH")
    if not os.path.exists(SLIDES):
        die("video/slides.html is missing")


def shot(n, out):
    url = f"file://{SLIDES}?clean=1#{n}"
    run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--force-device-scale-factor=1", f"--window-size={W},{H}",
         "--no-first-run", "--no-default-browser-check", "--disable-extensions",
         f"--user-data-dir={os.path.join(WORK, 'chrome')}",
         "--virtual-time-budget=2000", f"--screenshot={out}", url])
    if not os.path.exists(out) or os.path.getsize(out) < 20000:
        die(f"slide {n}: screenshot looks empty")
    return out


def speak(text, out):
    run(["say", "-v", VOICE, "-r", str(RATE), "-o", out, text])
    if not os.path.exists(out) or os.path.getsize(out) < 2000:
        die(f"no audio produced for: {text[:40]}...")
    return out


def clean_text(text):
    """Strip the `say` pause commands so the transcript reads as plain prose."""
    import re
    return re.sub(r"\s*\[\[slnc \d+\]\]\s*", " ", text).replace("  ", " ").strip()


def duration(path):
    p = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path], capture=True)
    return float(p.stdout.strip())


def segment(img, audio, out, speed):
    """Image + audio -> one clip. `speed` > 1 shortens the voice, preserving pitch."""
    raw = duration(audio)
    audible = raw / speed
    filt = f"atempo={speed:.4f},apad=pad_dur={PAD}" if speed > 1.0001 else f"apad=pad_dur={PAD}"
    run(["ffmpeg", "-y", "-loop", "1", "-i", img, "-i", audio,
         "-c:v", "libx264", "-preset", "medium", "-tune", "stillimage",
         "-pix_fmt", "yuv420p", "-r", "30", "-vf", f"scale={W}:{H}",
         "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
         "-af", filt, "-t", f"{audible + PAD:.2f}", out])
    return audible + PAD


def main():
    check_tools()
    os.makedirs(WORK, exist_ok=True)

    # 1. render every slide and record every line, then decide one tempo factor
    clips = []
    for idx, (slide, text) in enumerate(NARRATION, start=1):
        img = shot(slide, os.path.join(WORK, f"slide{slide:02d}.png"))
        aif = speak(text, os.path.join(WORK, f"line{idx:02d}.aiff"))
        clips.append((idx, slide, img, aif, duration(aif)))
        print(f"  {idx:02d}  slide {slide:02d}  {clips[-1][4]:5.1f}s spoken")

    raw_total = sum(d for *_, d in clips) + PAD * len(clips)
    speed = raw_total / TARGET if raw_total > TARGET else 1.0
    if speed > 1.0:
        print(f"\n  {raw_total:.0f}s of speech -> tightening x{speed:.3f} to hit {TARGET:.0f}s")

    # 2. cut the segments
    segs, total = [], 0.0
    for idx, slide, img, aif, _ in clips:
        seg = os.path.join(WORK, f"seg{idx:02d}.mp4")
        total += segment(img, aif, seg, speed)
        segs.append(seg)

    listfile = os.path.join(WORK, "concat.txt")
    with open(listfile, "w") as f:
        for s in segs:
            f.write(f"file '{s}'\n")

    # a plain-text transcript with timecodes: handy for captions, for editing
    # the wording, or for pasting into the spreadsheet / report appendix
    transcript = os.path.join(HERE, "narration.txt")
    t = 0.0
    with open(transcript, "w") as f:
        f.write(f"# video/explainer.mp4 - narration, {len(clips)} slides, "
                f"voice {VOICE} @ {RATE} wpm\n"
                f"# edit the text in build_video.py, then re-run it\n\n")
        for idx, slide, _img, _aif, raw in clips:
            line = raw / speed + PAD
            mm, ss = divmod(t, 60)
            f.write(f"[{mm:02.0f}:{ss:04.1f}]  slide {slide:02d}\n")
            f.write(clean_text(NARRATION[idx - 1][1]) + "\n\n")
            t += line
        f.write(f"# total {t:.1f}s\n")

    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
         "-c", "copy", "-movflags", "+faststart", OUT])

    mins, secs = divmod(round(total), 60)
    size = os.path.getsize(OUT) / 1_048_576
    print(f"\n  wrote {OUT}")
    print(f"  length {mins}m {secs:02d}s · {W}x{H} h264 + aac · {size:.1f} MB · "
          f"{len(clips)} slides · voice {VOICE} @ {RATE} wpm")


if __name__ == "__main__":
    main()

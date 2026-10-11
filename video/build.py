"""Render overlay/graphic frames from compose.html and assemble the submission video.
python build.py [render|assemble|all]"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
FF = r"C:\Users\fedem\.venvs\hackturin\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
DATA = Path(r"C:\Users\fedem\OneDrive\Desktop\Projects\hackturin-task1\data")
PHONE = DATA / "phone" / "VID_20261011_141209.mp4"
PHOTO = DATA / "phone" / "IMG_20261011_141341.jpg"
SCREEN = DATA / "screen_captures" / "Screencast from 10-11-2026 02_07_25 PM.webm"
RAW = ROOT / "raw"
FPS = 30
OUTNAME = "ocio_v3b.mp4"

# (scene id, seconds, background) ; background: None = full graphic, else (file, start, speed, kind)
SHOTS = [
    ("cold", 6.0, (PHONE, 10.5, 1.0, "video")),
    ("title", 5.0, None),
    ("problem", 6.0, None),
    ("hw", 7.0, (ROOT / "photo_upright.jpg", 0, 1.0, "photo")),
    ("light", 6.0, (PHONE, 25.0, 1.0, "video")),
    ("mode1a", 6.5, (RAW / "photocam.webm", 5.0, 1.0, "video")),
    ("mode1", 9.0, (RAW / "photoreal.webm", 43.0, 1.0, "video")),
    ("mode2", 9.0, (RAW / "site.webm", 8.5, 1.0, "video")),
    ("mode3", 12.0, (SCREEN, 190.0, 1.5, "squash")),
    ("reqs", 6.0, None),
    ("extras", 8.5, None),
    ("planner", 7.0, (RAW / "planner.webm", 3.0, 1.0, "video")),
    ("money", 7.5, None),
    ("qr", 3.0, (RAW / "share.webm", 7.0, 1.0, "video"), "none"),
    ("story", 8.5, (RAW / "citizen_mobile.webm", 3.0, 1.0, "phone")),
    ("omt", 2.5, None),
    ("inter", 7.0, (RAW / "intercam.webm", 4.0, 1.0, "video")),
    ("end", 6.0, None),
]


def render():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        page = b.new_page(viewport={"width": 1920, "height": 1080})
        page.goto((ROOT / "compose.html").as_uri())
        page.wait_for_timeout(500)
        only = set(sys.argv[2:])
        for sid, dur, bg, *ov in SHOTS:
            if ov or (only and sid not in only):
                continue
            out = ROOT / "frames" / sid
            out.mkdir(parents=True, exist_ok=True)
            for f in out.glob("*.png"):
                f.unlink()
            n = int(round(dur * FPS))
            for i in range(n):
                page.evaluate(f"renderAt('{sid}', {i / FPS}, {dur})")
                page.screenshot(path=str(out / f"{i:04d}.png"), omit_background=bg is not None)
            print("rendered", sid, n, flush=True)
        b.close()


def ff(*args):
    cmd = [FF, "-v", "error", "-y", *map(str, args)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stderr[-2000:])


def assemble():
    seg_dir = ROOT / "segs"
    seg_dir.mkdir(exist_ok=True)
    listing = []
    for sid, dur, bg, *ov in SHOTS:
        frames = ROOT / "frames" / sid / "%04d.png"
        out = seg_dir / f"{sid}.mp4"
        enc = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", FPS, "-an"]
        if bg is None:
            ff("-framerate", FPS, "-i", frames, "-t", dur, *enc, out)
        else:
            src, start, speed, kind = bg
            if kind == "phone":
                base = (f"color=c=0xf1e9da:s=1920x1080:r={FPS}:d={dur}[bg];"
                        f"[0:v]setpts=PTS-STARTPTS,scale=434:924,fps={FPS}[ph];[bg][ph]overlay=1268:78:shortest=1[base]")
                inputs = ["-ss", start, "-t", dur + 0.5, "-i", src]
            elif kind == "photo":
                base = (f"color=c=0x0e1115:s=1920x1080:r={FPS}:d={dur}[bg];"
                        f"[0:v]scale=562:1000,zoompan=z='1+0.0006*on':d={int(dur*FPS)}:s=562x1000:fps={FPS}[ph];"
                        f"[bg][ph]overlay=200:40[base]")
                inputs = ["-loop", "1", "-t", dur, "-i", src]
            else:
                fit = ("scale=1920:1080" if kind == "squash" else
                       "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080")
                base = f"[0:v]setpts=(PTS-STARTPTS)/{speed},{fit},fps={FPS}[base]"
                inputs = ["-ss", start, "-t", dur * speed + 0.5, "-i", src]
            if ov:
                ff(*inputs, "-filter_complex", base, "-map", "[base]", "-t", dur, *enc, out)
            else:
                ff(*inputs, "-framerate", FPS, "-i", frames,
                   "-filter_complex", base + ";[base][1:v]overlay=0:0:shortest=1[v]", "-map", "[v]", "-t", dur, *enc, out)
        listing.append(f"file '{out.as_posix()}'")
        print("segment", sid, flush=True)
    X = 0.45  # crossfade seconds
    durs = [shot[1] for shot in SHOTS]
    inputs, chain = [], []
    for sid, *_ in SHOTS:
        inputs += ["-noautorotate", "-i", seg_dir / f"{sid}.mp4"]
    prev, offset = "[0:v]", 0.0
    for k in range(1, len(SHOTS)):
        offset += durs[k - 1] - X
        out_label = f"[x{k}]"
        chain.append(f"{prev}[{k}:v]xfade=transition=fade:duration={X}:offset={offset:.3f}{out_label}")
        prev = out_label
    total = sum(durs) - X * (len(SHOTS) - 1)
    inputs += ["-i", ROOT / "music.wav"]
    ff(*inputs, "-filter_complex", ";".join(chain), "-map", prev, "-map", f"{len(SHOTS)}:a",
       "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", FPS,
       "-c:a", "aac", "-b:a", "192k", "-af", f"afade=t=out:st={total - 2.5}:d=2.5", "-t", total, ROOT / "out" / OUTNAME)
    print("video", ROOT / "out" / OUTNAME, total, "s")


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else "all"
    if step in ("render", "all"):
        render()
    if step in ("assemble", "all"):
        assemble()

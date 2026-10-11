"""Build a self-contained App Lab folder without editing or flashing an installed app."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "firmware" / "crosswalk_mcu"


def prepare(destination, profile="grove", oled=True):
    if profile not in ("grove", "original"):
        raise ValueError("profile must be grove or original")
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite an app: {destination}; choose a new folder")
    if destination.is_relative_to(SOURCE):
        raise ValueError("output must be outside the firmware source folder")
    shutil.copytree(SOURCE, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    sketch = destination / "sketch" / "sketch.ino"
    grove = profile == "grove"
    selected_oled = grove and oled
    prefix = f"#define OCCHIO_GROVE_PROFILE {int(grove)}\n#define OCCHIO_HAS_OLED {int(selected_oled)}\n"
    sketch.write_text(prefix + sketch.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    if selected_oled:
        dependencies = destination / "sketch" / "sketch.yaml"
        text = dependencies.read_text(encoding="utf-8")
        dependencies.write_text(text.replace("    libraries:\n", "    libraries:\n      - U8g2 (2.36.5)\n"),
                                encoding="utf-8", newline="\n")
    # Systemd owns camera capture. The MCU app must never start a second pipeline.
    (destination / "python" / "main.py").write_text(
        '"""Keep the MCU app alive; the occhio service owns CAM0 and inference."""\n'
        "from arduino.app_utils import App\n\nApp.run()\n", encoding="utf-8", newline="\n")
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                           stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = None
    files = {p.relative_to(destination).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(destination.rglob("*")) if p.is_file()}
    manifest = {"profile": profile, "oled": selected_oled, "revision": revision, "files_sha256": files,
                "wiring_reference": "docs/HANDOFF_LIVE_GPIO.md (operator correction 2026-10-11)" if grove else "docs/HARDWARE.md"}
    (destination / "occhio-build.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("grove", "original"), default="grove")
    parser.add_argument("--no-oled", action="store_true", help="GPIO diagnosis only; disables the I2C display")
    parser.add_argument("--out", required=True, help="new output folder; existing apps are never overwritten")
    args = parser.parse_args()
    manifest = prepare(args.out, args.profile, not args.no_oled)
    print(f"Prepared {args.profile} MCU app at {Path(args.out).resolve()} (OLED: {manifest['oled']})")
    print("Nothing was flashed or started. See docs/HANDOFF_LIVE_GPIO.md for installation and verification.")


if __name__ == "__main__":
    main()

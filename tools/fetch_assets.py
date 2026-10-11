"""Fetch everything that is not in git: sample videos + exported detector models.

    python tools/fetch_assets.py            # videos + yolo11n/yolo26n ONNX (256/320/416, fp32+int8) + NCNN 320
    python tools/fetch_assets.py --videos   # only the sample videos
    python tools/fetch_assets.py --models   # only the models (needs requirements-dev.txt: ultralytics, onnx, ncnn)

Weights come from Ultralytics' public releases (downloaded automatically by tools/export_models.py), so the files are
bit-for-bit what the board uses. Real site footage does not exist yet: it will be recorded on site with
tools/record.py and shared separately (it contains people's faces - never commit it).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEOS = {
    "person-bicycle-car-detection.mp4": "https://github.com/intel-iot-devkit/sample-videos/raw/master/person-bicycle-car-detection.mp4",
    "car-detection.mp4": "https://github.com/intel-iot-devkit/sample-videos/raw/master/car-detection.mp4",
    "people-detection.mp4": "https://github.com/intel-iot-devkit/sample-videos/raw/master/people-detection.mp4",
    "vtest.avi": "https://github.com/opencv/opencv/raw/4.x/samples/data/vtest.avi",
}


def fetch_videos():
    d = os.path.join(ROOT, "data", "videos")
    os.makedirs(d, exist_ok=True)
    for name, url in VIDEOS.items():
        dst = os.path.join(d, name)
        if os.path.exists(dst) and os.path.getsize(dst) > 100_000:
            print("ok  ", name)
            continue
        print("get ", name)
        urllib.request.urlretrieve(url, dst)


def fetch_models():
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "export_models.py"), "--weights", "yolo11n.pt", "yolo26n.pt",
                    "--sizes", "256", "320", "416", "--ncnn-sizes", "320", "--int8-onnx",
                    "--calib", os.path.join(ROOT, "data", "videos", "vtest.avi"),
                    os.path.join(ROOT, "data", "videos", "people-detection.mp4"),
                    os.path.join(ROOT, "data", "videos", "person-bicycle-car-detection.mp4")], check=True, cwd=ROOT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--videos", action="store_true")
    ap.add_argument("--models", action="store_true")
    a = ap.parse_args()
    both = not (a.videos or a.models)
    if a.videos or both:
        fetch_videos()
    if a.models or both:
        fetch_models()
    print("done. models in models/, videos in data/videos/")


if __name__ == "__main__":
    main()

"""Run under libcamerify on UNO Q; record capture metadata, never images."""
import argparse
import json
import resource
import time
from pathlib import Path

from crosswalk.sources import CameraSource

parser = argparse.ArgumentParser()
parser.add_argument("--out", required=True)
parser.add_argument("--seconds", type=float, default=20)
args = parser.parse_args()
config = dict(device=0, width=640, height=480, fps=30, fourcc=None,
              stereo=None, resize_width=None)
source = CameraSource(config)
start = time.monotonic()
cpu_start = resource.getrusage(resource.RUSAGE_SELF)
sequence, received, missing = -1, 0, 0
shapes, intensity = set(), []
try:
    while time.monotonic() - start < args.seconds:
        frame, timestamp, sequence = source.read(sequence)
        if frame is None:
            missing += 1
        else:
            received += 1
            shapes.add(tuple(frame.shape))
            if received % 30 == 0:
                intensity.append(dict(mean=float(frame.mean()), std=float(frame.std())))
    elapsed = time.monotonic() - start
    cpu_end = resource.getrusage(resource.RUSAGE_SELF)
    cpu_s = cpu_end.ru_utime + cpu_end.ru_stime - cpu_start.ru_utime - cpu_start.ru_stime
    result = dict(request=config, obtained=source.stats(), shapes=sorted(shapes),
                  received=received, missing_reads=missing, elapsed_s=elapsed,
                  received_hz=received / elapsed, process_cpu_one_core_pct=100 * cpu_s / elapsed,
                  intensity_samples=intensity)
    Path(args.out).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "intensity_samples"}), flush=True)
finally:
    source.close()

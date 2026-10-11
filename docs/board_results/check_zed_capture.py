"""Board-only camera verification; saves metadata, never camera images."""
import json
import resource
import time
from pathlib import Path

from crosswalk.sources import CameraSource
from crosswalk.telemetry import Telemetry

rows = []
for width, height, resize in [(1344, 376, None), (2560, 720, 640)]:
    cfg = dict(device="/dev/v4l/by-id/usb-Technologies__Inc._ZED-M-video-index0",
               width=width, height=height, fps=30, fourcc="YUYV", stereo="left", resize_width=resize)
    source = CameraSource(cfg)
    telemetry = Telemetry()
    begin = time.monotonic()
    cpu_begin = resource.getrusage(resource.RUSAGE_SELF)
    seq, shapes, samples, missing = -1, set(), [], 0
    try:
        while time.monotonic() - begin < 20:
            frame, timestamp, seq = source.read(seq)
            if frame is None:
                missing += 1
            else:
                shapes.add(tuple(frame.shape))
            samples.append(telemetry.snapshot())
        elapsed = time.monotonic() - begin
        cpu_end = resource.getrusage(resource.RUSAGE_SELF)
        cpu_seconds = cpu_end.ru_utime + cpu_end.ru_stime - cpu_begin.ru_utime - cpu_begin.ru_stime
        row = dict(request=cfg, obtained=source.stats(), shapes=sorted(shapes), missing_reads=missing,
                   elapsed_s=round(elapsed, 2), process_cpu_one_core_pct=round(100 * cpu_seconds / elapsed, 1),
                   system_samples=samples[::30])
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if k != "system_samples"}), flush=True)
    finally:
        source.close()
Path("docs/board_results/zed_capture.json").write_text(json.dumps(rows, indent=2) + "\n")

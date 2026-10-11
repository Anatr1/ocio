"""Board verification artefact: sample named thermal zones and core frequencies, stdlib only."""
import argparse
import csv
import glob
import pathlib
import time

ap = argparse.ArgumentParser()
ap.add_argument("--seconds", type=float, default=315)
ap.add_argument("--out", required=True)
ap.add_argument("--pid", type=int, help="optional pipeline PID for process RSS, not system RAM")
a = ap.parse_args()
zones = {pathlib.Path(z, "type").read_text().strip(): pathlib.Path(z, "temp")
         for z in glob.glob("/sys/class/thermal/thermal_zone*")}
freqs = sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq"))
fields = ["elapsed_s", "utc", "cpuss0_c", "cpuss1_c", "max_zone_c", "process_rss_mb", "process_swap_mb"] + [f"cpu{i}_khz" for i in range(len(freqs))]
start = time.monotonic()
with open(a.out, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    while time.monotonic() - start < a.seconds:
        temps = {name: int(p.read_text()) / 1000 for name, p in zones.items()}
        row = {"elapsed_s": round(time.monotonic() - start, 1),
               "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "cpuss0_c": temps.get("cpuss0-thermal"), "cpuss1_c": temps.get("cpuss1-thermal"),
               "max_zone_c": max(temps.values())}
        row.update({f"cpu{i}_khz": int(pathlib.Path(p).read_text()) for i, p in enumerate(freqs)})
        if a.pid:
            try:
                status = pathlib.Path(f"/proc/{a.pid}/status").read_text().splitlines()
                mem = {line.split(":")[0]: int(line.split()[1]) / 1024
                       for line in status if line.startswith(("VmRSS:", "VmSwap:"))}
                row.update(process_rss_mb=mem.get("VmRSS"), process_swap_mb=mem.get("VmSwap"))
            except FileNotFoundError:
                pass
        w.writerow(row)
        f.flush()
        time.sleep(5)

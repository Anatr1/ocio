"""Launch a simulated fleet of crosswalks in Turin + the hub (laptop demo of scalability).

    python tools/demo_fleet.py                                  # 3 simulated nodes + hub on :9000
    python tools/demo_fleet.py --board http://192.168.8.10:8000 # add the real UNO Q node to the fleet
Ctrl+C stops everything.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NODES = [
    # (port, scenario, seed, id, name, lat, lon, signal mode)
    (8101, "rush", 11, "to-portanuova", "C.so Vittorio Emanuele II - Porta Nuova", 45.0623, 7.6786, "adaptive"),
    (8102, "dangerous", 12, "to-grosseto", "C.so Grosseto - zebra", 45.0985, 7.6650, "beacon"),
    (8103, "mixed", 13, "to-polito", "C.so Duca degli Abruzzi - Politecnico", 45.0630, 7.6610, "fixed"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", nargs="*", default=[], help="URLs of real nodes to include")
    ap.add_argument("--port", type=int, default=9000)
    args = ap.parse_args()
    procs = []
    py = sys.executable
    for port, scen, seed, nid, name, lat, lon, mode in NODES:
        cmd = [py, "-m", "crosswalk", "--sim", scen, "--seed", str(seed), "--port", str(port),
               "--set", f"node.id={nid}", "--set", f"node.name={name}", "--set", f"node.geo.lat={lat}",
               "--set", f"node.geo.lon={lon}", "--set", f"signal.mode={mode}", "--set", "log.dir="]
        procs.append(subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        print(f"[fleet] {nid} ({scen}) on :{port}")
    time.sleep(2)
    urls = [f"http://localhost:{p[0]}" for p in NODES] + args.board
    procs.append(subprocess.Popen([py, os.path.join(ROOT, "tools", "hub.py"), "--port", str(args.port), "--nodes", *urls], cwd=ROOT))
    print(f"[fleet] hub -> http://localhost:{args.port}/fleet.html")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()


if __name__ == "__main__":
    main()

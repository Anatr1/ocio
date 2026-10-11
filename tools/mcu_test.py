"""Hardware smoke test for the MCU side (run ON THE BOARD over SSH after flashing firmware/crosswalk_mcu).

    python3 tools/mcu_test.py            # cycles lamps, beacon, buzzer and LED-matrix pages, prints button presses
    python3 tools/mcu_test.py --watchdog # stops heartbeats to show the fail-safe flashing amber
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crosswalk.mcu import RouterClient, render_icon, render_number, to_bytes  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--socket", default="/var/run/arduino-router.sock")
    ap.add_argument("--watchdog", action="store_true")
    args = ap.parse_args()
    c = RouterClient(args.socket, timeout=1.0)
    c.handlers["ped_button"] = lambda *a: print("  >>> push button pressed", a)
    c.connect()
    t0 = time.perf_counter()
    print("ping ->", c.call("ping"), f"({(time.perf_counter() - t0) * 1000:.1f} ms round trip)")

    def hb():
        c.call("heartbeat", int(time.monotonic() * 1000) & 0x7FFFFFFF)

    steps = [
        ("vehicles GREEN, peds RED", (3, 1), 0, render_icon("car")),
        ("vehicles YELLOW", (2, 1), 0, render_icon("car")),
        ("all RED", (1, 1), 0, render_number(0)),
        ("peds GREEN (walk ticks)", (1, 2), 0, render_icon("walk")),
        ("peds FLASHING (clearance ticks)", (1, 3), 0, render_number(5)),
        ("beacon caution", (0, 0), 1, render_icon("walk")),
        ("beacon DANGER", (0, 0), 2, render_icon("warn")),
        ("count page", (3, 1), 0, render_number(123)),
    ]
    for name, (veh, ped), warn, grid in steps:
        print(name)
        c.call("set_signal", veh, ped)
        c.call("set_warning", warn)
        c.call("draw", to_bytes(grid))
        for _ in range(6):
            hb()
            time.sleep(0.5)
    if args.watchdog:
        print("stopping heartbeats: the lamps must go to FLASHING AMBER within 2 s (fail-safe)")
        time.sleep(6)
        print("resuming heartbeats")
        for _ in range(6):
            hb()
            time.sleep(0.5)
    c.call("set_warning", 0)
    c.call("set_signal", 3, 1)
    print("done - press the push button now to test the notification (Ctrl+C to quit)")
    try:
        while True:
            hb()
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

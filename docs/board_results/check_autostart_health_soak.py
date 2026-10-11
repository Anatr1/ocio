"""Companion to tools/soak_monitor.py: HTTP 503, freshness, reopen and process checks."""
import argparse
import csv
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument('--minutes', type=float, default=30)
parser.add_argument('--out', required=True)
args = parser.parse_args()
fields = ['utc', 'elapsed_s', 'http_status', 'ok', 'vision_age_s', 'failsafe', 'mcu_connected',
          'mcu_error', 'frame_age_s', 'camera_reopens', 'frames', 'source_t', 'pid', 'rss_mib',
          'swap_mib', 'request_error']

def request(path):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000' + path, timeout=2) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)

start = time.monotonic()
with Path(args.out).open('w', newline='') as output:
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    while time.monotonic() - start < args.minutes * 60:
        row = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), elapsed_s=time.monotonic() - start)
        try:
            status, health = request('/api/health')
            row.update(http_status=status, **{k: health.get(k) for k in ['ok', 'vision_age_s', 'failsafe', 'mcu_connected']})
            _, state = request('/api/state')
            perf = state.get('perf', {})
            row.update(source_t=state.get('t'), mcu_error=state.get('mcu', {}).get('error'),
                       **{k: perf.get(k) for k in ['frame_age_s', 'camera_reopens', 'frames']})
            pid = int(subprocess.check_output(['systemctl', 'show', 'occhio', '-p', 'MainPID', '--value'], text=True))
            row['pid'] = pid
            for line in Path(f'/proc/{pid}/status').read_text().splitlines():
                if line.startswith('VmRSS:'):
                    row['rss_mib'] = int(line.split()[1]) / 1024
                elif line.startswith('VmSwap:'):
                    row['swap_mib'] = int(line.split()[1]) / 1024
        except Exception as error:
            row['request_error'] = f'{type(error).__name__}: {error}'
        writer.writerow(row)
        output.flush()
        time.sleep(5)
    os.fsync(output.fileno())
print('Health/freshness monitor finished', flush=True)

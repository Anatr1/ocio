"""Temporary boot observer: kernel-boot-to-health timing, never camera media."""
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

out = Path('/home/arduino/occhio/docs/board_results/autostart_boot.jsonl')
boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
with out.open('w') as stream:
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        row = dict(utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                   boot_id=boot_id, boot_elapsed_s=time.clock_gettime(time.CLOCK_BOOTTIME))
        try:
            with urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=0.7) as response:
                row.update(http_status=response.status, health=json.load(response))
        except urllib.error.HTTPError as error:
            row.update(http_status=error.code, health=json.load(error))
        except Exception as error:
            row['error'] = f'{type(error).__name__}: {error}'
        row['sample_done_boot_s'] = time.clock_gettime(time.CLOCK_BOOTTIME)
        stream.write(json.dumps(row) + '\n')
        stream.flush()
        if row.get('health', {}).get('ok') and row['health'].get('mcu_connected') and not row['health'].get('failsafe'):
            os.fsync(stream.fileno())
            print(json.dumps(row), flush=True)
            break
        time.sleep(0.25)
    else:
        os.fsync(stream.fileno())
        raise SystemExit('No fresh-vision/MCU health within the 300-second observation window')

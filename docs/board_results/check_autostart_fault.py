"""Board test only: SIGSTOP, SIGKILL, or simulated failed CAM0 reads; save metadata."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.error
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument('mode', choices=['freeze', 'crash', 'camera'])
parser.add_argument('--out', required=True)
parser.add_argument('--pid', type=int)
args = parser.parse_args()
marker = Path('/tmp/occhio-cam0-read-failure')
start = time.monotonic()

def request(path):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000' + path, timeout=0.7) as response:
            return dict(http_status=response.status, body=json.load(response))
    except urllib.error.HTTPError as error:
        return dict(http_status=error.code, body=json.load(error))
    except Exception as error:
        return dict(error=f'{type(error).__name__}: {error}')

with Path(args.out).open('w') as output:
    def sample(phase, **extra):
        row = dict(phase=phase, elapsed_s=time.monotonic() - start,
                   utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), **extra)
        row['health'] = request('/api/health')
        if 'http_status' in row['health']:
            state = request('/api/state').get('body', {})
            row.update(t=state.get('t'), perf=state.get('perf'),
                       mcu={k: state.get('mcu', {}).get(k) for k in ['connected', 'failsafe', 'rtt_ms', 'error']})
        output.write(json.dumps(row) + '\n')
        output.flush()
        return row

    def healthy(row):
        health = row['health'].get('body', {})
        return health.get('ok') and health.get('mcu_connected') and not health.get('failsafe')

    before = sample('before')
    if not healthy(before):
        raise SystemExit('Refusing fault test: node is not initially healthy with MCU connected')
    pid = args.pid or int(subprocess.check_output(['systemctl', 'show', 'occhio', '-p', 'MainPID', '--value'], text=True))
    command = Path(f'/proc/{pid}/cmdline').read_bytes()
    if pid <= 1 or b'crosswalk' not in command or b'board_imx219.yaml' not in command:
        raise SystemExit(f'Refusing to signal an unexpected process: {pid}')
    trigger = time.monotonic()
    if args.mode == 'freeze':
        # Independent backstop even if this helper is killed: the node cannot remain SIGSTOPed.
        subprocess.Popen(['/bin/sh', '-c', f'sleep 15; kill -CONT {pid}'], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        os.kill(pid, signal.SIGSTOP)
        try:
            while time.monotonic() - trigger < 8:
                sample('frozen', pid=pid, process_state=Path(f'/proc/{pid}/stat').read_text().split(') ')[1].split()[0])
                time.sleep(1)
        finally:
            os.kill(pid, signal.SIGCONT)
    elif args.mode == 'crash':
        os.kill(pid, signal.SIGKILL)
    else:
        marker.touch(exist_ok=False)
        try:
            while time.monotonic() - trigger < 8:
                sample('camera_read_failure', pid=pid)
                time.sleep(0.25)
        finally:
            marker.unlink(missing_ok=True)
    released = time.monotonic()
    deadline = released + 25
    first_healthy = None
    while time.monotonic() < deadline:
        row = sample('recovery', trigger_elapsed_s=trigger - start,
                     release_elapsed_s=released - start, since_trigger_s=time.monotonic() - trigger,
                     since_release_s=time.monotonic() - released)
        if healthy(row):
            if first_healthy is None:
                first_healthy = time.monotonic() - released
            # Health can be fresh before the current iteration publishes its state snapshot.
            # Confirm actual capture progress and a reopen counter for the camera-read test.
            if args.mode == 'camera':
                perf = row.get('perf') or {}
                if (perf.get('frames', 0) <= before.get('perf', {}).get('frames', 0)
                        or perf.get('camera_reopens', 0) < 1):
                    time.sleep(0.25)
                    continue
            current_pid = subprocess.check_output(['systemctl', 'show', 'occhio', '-p', 'MainPID', '--value'], text=True).strip()
            summary = dict(mode=args.mode, initial_pid=pid, service_pid_after=current_pid,
                           first_healthy_since_release_s=first_healthy,
                           camera_reopens=(row.get('perf') or {}).get('camera_reopens'),
                           recovery_since_trigger_s=time.monotonic() - trigger,
                           recovery_since_release_s=time.monotonic() - released)
            output.write(json.dumps(dict(phase='summary', **summary)) + '\n')
            output.flush()
            os.fsync(output.fileno())
            print(json.dumps(summary), flush=True)
            break
        time.sleep(0.25)
    else:
        raise SystemExit('No healthy vision/MCU recovery within 25 seconds')

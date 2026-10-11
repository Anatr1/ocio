"""Read-only MCU sampling around a bounded exact-service freeze/crash test.

Run on the board with sudo and its venv. Never sends a heartbeat or signal RPC.
No physical output or timing pass is inferred from these samples.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.request import urlopen
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from crosswalk.mcu import RouterClient

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('mode', choices=['freeze', 'crash'])
ap.add_argument('--out', required=True)
args = ap.parse_args()


def request(path):
    try:
        with urlopen('http://127.0.0.1:8000'+path, timeout=.4) as r:
            return json.load(r)
    except Exception as e:
        return {'error': str(e)}


pid = int(subprocess.check_output(['systemctl', 'show', 'occhio', '-p', 'MainPID', '--value'], text=True))
if pid <= 1:
    raise SystemExit('No service PID')
command = Path(f'/proc/{pid}/cmdline').read_bytes()
if b'crosswalk' not in command or b'configs/board_grove_local.yaml' not in command:
    raise SystemExit('Refusing to signal an unexpected process')
health = request('/api/health')
if not (health.get('ok') and health.get('mcu_connected') and not health.get('failsafe')):
    raise SystemExit('Initially unhealthy; refusing fault test')
client = RouterClient('/var/run/arduino-router.sock', timeout=1)
client.connect()
start = time.monotonic()
fs_seen = False
resumed = args.mode != 'freeze'
with Path(args.out).open('x') as out:
    def sample(phase, http=True):
        row = {'phase': phase, 'elapsed_s': time.monotonic()-start, 'utc_epoch': time.time(), 'initial_pid': pid,
               'firmware_status': client.call('get_status')}
        if http:
            row['health'] = request('/api/health')
            state = request('/api/state')
            row.update(perf=state.get('perf'), counts=state.get('counts'), mcu=state.get('mcu'), signal=state.get('signal'))
        out.write(json.dumps(row)+'\n'); out.flush()
        return row
    before = sample('before')
    trigger = time.monotonic()
    out.write(json.dumps({'phase':'trigger', 'elapsed_s':trigger-start, 'mode':args.mode})+'\n'); out.flush()
    if args.mode == 'freeze':
        subprocess.Popen(['/bin/sh','-c',f'sleep 15; kill -CONT {pid}'], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    os.kill(pid, signal.SIGSTOP if args.mode == 'freeze' else signal.SIGKILL)
    try:
        while time.monotonic()-trigger < 8:
            row = sample('frozen' if args.mode == 'freeze' else 'crashed', http=args.mode != 'freeze')
            fs_seen |= row['firmware_status'][2] == 1
            time.sleep(.1)
    finally:
        if args.mode == 'freeze':
            os.kill(pid, signal.SIGCONT); resumed = True
    release = time.monotonic()
    deadline = release+30
    while time.monotonic() < deadline:
        row = sample('recovery')
        h = row['health']
        if h.get('ok') and h.get('mcu_connected') and not h.get('failsafe') and row['firmware_status'][2] == 0:
            current_pid = int(subprocess.check_output(['systemctl','show','occhio','-p','MainPID','--value'], text=True))
            summary = {'mode':args.mode, 'failsafe_rpc_observed':fs_seen, 'initial_pid':pid,'recovered_pid':current_pid,
                       'recovery_since_trigger_s':time.monotonic()-trigger, 'recovery_since_release_s':time.monotonic()-release,
                       'physical_outputs':'UNMEASURED', 'software_pass':fs_seen and (current_pid==pid if args.mode=='freeze' else current_pid!=pid)}
            out.write(json.dumps({'phase':'summary',**summary})+'\n'); out.flush(); os.fsync(out.fileno())
            print(json.dumps(summary),flush=True)
            if not summary['software_pass']:
                raise SystemExit(1)
            break
        time.sleep(.25)
    else:
        raise SystemExit('No healthy recovery within 30 seconds')
client.close()

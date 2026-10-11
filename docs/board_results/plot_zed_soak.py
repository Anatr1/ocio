"""Render the recovered board stability data; source timestamps, not synthetic samples."""
import csv
import datetime as dt
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

root = Path(__file__).resolve().parent
states = list(csv.DictReader((root / 'zed_uncalibrated_30min.csv').open()))
cpu = list(csv.DictReader((root / 'zed_low_cpu.csv').open()))
start = dt.datetime.fromisoformat('2026-10-10T13:54:32+00:00')
end = dt.datetime.fromisoformat('2026-10-10T14:25:29+00:00')
stall = dt.datetime.fromisoformat('2026-10-10T14:24:19+00:00')
def mins(t):
    return (t - start).total_seconds() / 60
sx = [mins(dt.datetime.fromisoformat('2026-10-10T' + r['wall'] + '+00:00')) for r in states]
cpu = [r for r in cpu if dt.datetime.fromisoformat(r['utc'].replace('Z', '+00:00')) <= end]
cx = [mins(dt.datetime.fromisoformat(r['utc'].replace('Z', '+00:00'))) for r in cpu]
plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True, constrained_layout=True)
fig.suptitle('ZED live run: camera state froze before the monitor finished\nNCNN YOLO11n 320 / 4 threads · 672×376 left eye · no heatsink/fan · ambient unknown', fontsize=13)
axes[0].plot(sx, [float(r['det_hz']) for r in states], color='#176b9c', linewidth=1.4, label='Reported detector Hz')
axes[0].set_ylabel('Detector Hz')
axes[0].legend(loc='lower left')
for field, label, color in [('cpuss0_c', 'cpuss0', '#bf3c29'), ('cpuss1_c', 'cpuss1', '#da9a1b')]:
    axes[1].plot(cx, [float(r[field]) for r in cpu], label=label, color=color, linewidth=1.4)
axes[1].set_ylabel('CPU temperature (°C)')
axes[1].legend(loc='lower left')
axes[2].plot(cx, [float(r['process_rss_mb']) if r['process_rss_mb'] else float('nan') for r in cpu], color='#36754b', linewidth=1.4)
axes[2].set_ylabel('Process RSS (MiB)')
axes[2].set_xlabel('Minutes since pipeline start (13:54:32 UTC)')
for ax in axes:
    ax.axvspan(mins(stall), mins(end), color='#cf4444', alpha=0.17)
    ax.grid(alpha=0.2)
    ax.set_xlim(0, mins(end))
axes[0].annotate('Final 70 s: stale camera state,\nMCU heartbeat still responding', xy=(mins(stall), 7.9), xytext=(18, 10.3), arrowprops={'arrowstyle': '->', 'color': '#9b2525'}, color='#9b2525')
axes[0].set_ylim(0, 12)
fig.savefig(root / 'zed_live_soak_plot.png', dpi=160)

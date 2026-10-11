"""Warm, upbeat product-launch bed: FM electric piano, sub bass, soft drums, bell hook, convolution reverb.
Generated from scratch (no samples). python music2.py SECONDS"""
import sys
import wave

import numpy as np
from scipy.signal import fftconvolve, butter, sosfilt

SR = 44100
BPM = 104
BEAT = 60 / BPM
BAR = 4 * BEAT
LENGTH = float(sys.argv[1]) if len(sys.argv) > 1 else 115.0
N = int(LENGTH * SR) + SR
rng = np.random.default_rng(7)
hz = lambda m: 440.0 * 2 ** ((m - 69) / 12)
lp = lambda x, f: sosfilt(butter(2, f, "low", fs=SR, output="sos"), x)
hp = lambda x, f: sosfilt(butter(2, f, "high", fs=SR, output="sos"), x)


def add(buf, t, sig, g):
    i = int(t * SR)
    j = min(len(buf), i + len(sig))
    if 0 <= i < len(buf):
        buf[i:j] += g * sig[: j - i]


def epiano(m, dur):
    n = int((dur + 1.2) * SR)
    t = np.arange(n) / SR
    f = hz(m)
    idx = 2.2 * np.exp(-t * 6)
    s = np.sin(2 * np.pi * f * t + idx * np.sin(2 * np.pi * f * t))
    s += 0.25 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t * 3)
    env = np.minimum(1, t / 0.004) * np.exp(-t * 1.6) * np.clip((dur + 1.2 - t) / 0.3, 0, 1)
    return s * env


def bell(m, dur):
    n = int((dur + 1.5) * SR)
    t = np.arange(n) / SR
    f = hz(m)
    s = np.sin(2 * np.pi * f * t + 1.5 * np.exp(-t * 4) * np.sin(2 * np.pi * 3.5 * f * t))
    return s * np.minimum(1, t / 0.002) * np.exp(-t * 2.5)


def sub(m, dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = np.sin(2 * np.pi * hz(m) * t) + 0.15 * np.sin(4 * np.pi * hz(m) * t)
    return s * np.minimum(1, t / 0.01) * np.clip((dur - t) / 0.05, 0, 1)


def kick():
    n = int(0.4 * SR)
    t = np.arange(n) / SR
    f = 45 + 90 * np.exp(-t * 35)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7)


def noise_hit(dur, decay, lo, hi):
    n = int(dur * SR)
    s = hp(lp(rng.standard_normal(n), hi), lo)
    return s * np.exp(-np.arange(n) / SR * decay)


K = kick()
HAT = noise_hit(0.08, 55, 7000, 15000)
SHAKER = noise_hit(0.12, 30, 5000, 12000)
SNAP = noise_hit(0.25, 16, 1500, 6000)
CHORDS = [[48, 55, 59, 64, 67], [45, 52, 55, 60, 64, 71], [41, 48, 52, 57, 64], [43, 50, 55, 59, 62, 69]]
ROOTS = [36, 33, 29, 31]
HOOK = [76, 79, 81, 79, 76, 74, 72, 74]

keys = np.zeros(N); bass = np.zeros(N); drums = np.zeros(N); bells = np.zeros(N)
bars = int(LENGTH / BAR) + 1
for b in range(bars):
    t0 = b * BAR
    ci = b % 4
    section = "intro" if b < 4 else "verse" if b < 16 else "chorus" if b < 28 else "verse2" if b < 36 else "chorus"
    end = t0 > LENGTH - 2 * BAR
    # keys: rhythmic comping (1, 2&, 4) with voicing
    for beat_pos in ((0, 1.4), (1.5, 0.9), (3.0, 0.9)):
        for m in CHORDS[ci]:
            add(keys, t0 + beat_pos[0] * BEAT, epiano(m + 12, beat_pos[1] * BEAT), 0.045)
    if section != "intro":
        for k, (pos, dur) in enumerate(((0, 1.5), (1.5, 0.5), (2, 1.5), (3.5, 0.5))):
            add(bass, t0 + pos * BEAT, sub(ROOTS[ci] + (0 if k % 2 == 0 else 12), dur * BEAT * 0.95), 0.32)
        for k in range(4):
            add(drums, t0 + k * BEAT, K, 0.6 if section.startswith("chorus") else 0.45)
            if k in (1, 3):
                add(drums, t0 + k * BEAT, SNAP, 0.22)
        for k in range(8):
            add(drums, t0 + k * BEAT / 2 + BEAT / 4 * (k % 2), HAT if k % 2 else SHAKER, 0.07)
    if section.startswith("chorus") and not end:
        for k, m in enumerate(HOOK):
            add(bells, t0 + k * BEAT / 2, bell(m, BEAT / 2), 0.10 if k % 2 == 0 else 0.07)

wet = keys + 0.8 * bells
ir_n = int(2.6 * SR)
ir = rng.standard_normal(ir_n) * np.exp(-np.arange(ir_n) / SR * 2.4)
ir = lp(ir, 6000)
ir /= np.sqrt(np.sum(ir ** 2))
reverb = fftconvolve(wet, ir)[:N] * 0.35
pump = np.ones(N)
for b in range(4, bars):
    for k in range(4):
        i = int((b * BAR + k * BEAT) * SR)
        j = min(N, i + int(0.22 * SR))
        if i < N:
            pump[i:j] = np.minimum(pump[i:j], 0.65 + 0.35 * np.linspace(0, 1, j - i))
mix = (keys + bells + reverb) * pump + bass + drums
mix = hp(mix, 30)[: int(LENGTH * SR)]
n = len(mix)
mix *= np.minimum(1, np.arange(n) / (1.5 * SR)) * np.clip((n - np.arange(n)) / (3.0 * SR), 0, 1)
mix = np.tanh(1.2 * mix / (np.max(np.abs(mix)) + 1e-9)) * 0.9
left = mix + 0.12 * fftconvolve(wet[: n], ir[::2] * 0.5)[:n] / (np.max(np.abs(mix)) + 1e-9) * 0
right = np.roll(mix, int(0.009 * SR))
stereo = np.stack([0.92 * mix + 0.08 * right, 0.92 * right + 0.08 * mix], axis=1)
stereo /= np.max(np.abs(stereo)) / 0.9
with wave.open("music.wav", "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((stereo * 32767).astype(np.int16).tobytes())
print("music.wav", LENGTH)

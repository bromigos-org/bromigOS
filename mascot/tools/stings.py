#!/usr/bin/env python3
"""Den TV bump stings, synthesised from scratch in numpy (no samples, no model: licence-clean, our own code).

STATIC never speaks; his sound is radio: crackle, a dial finding a station, a lamp's tone, a hum.
Each sting is short (0.8-2.2 s), sits at about -18 dBFS RMS (soft-limited under -1 dBFS) and fades in and out with no click.

    python3 stings.py OUTDIR      -> OUTDIR/<name>.ogg (Opus, 48 kHz stereo) and a .wav beside it
"""
import os
import subprocess
import sys
import wave

import numpy as np

SR = 48000
RNG = np.random.default_rng(142590)        # 142.59: the roll-call band, as the seed


def t_(sec):
    return np.arange(int(sec * SR)) / SR


def env(n, a=0.005, r=0.05):
    e = np.ones(n)
    na, nr = max(1, int(a * SR)), max(1, int(r * SR))
    e[:na] = np.linspace(0, 1, na)
    e[-nr:] *= np.linspace(1, 0, nr)
    return e


def onepole(x, cutoff):
    """A one-pole low-pass (cutoff in Hz), vectorised by an exponential filter via lfilter-free recursion."""
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):
        acc = (1 - a) * v + a * acc
        y[i] = acc
    return y


def bandnoise(n, lo, hi):
    """Noise between lo and hi Hz, through the FFT."""
    spec = np.fft.rfft(RNG.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    spec[(f < lo) | (f > hi)] = 0
    x = np.fft.irfft(spec, n)
    return x / (np.abs(x).max() + 1e-9)


def crackle(sec, density=60, lo=900, hi=7000, tail=0.004):
    """Radio crackle: sparse clicks with tiny decays, plus a bed of band-limited hiss."""
    n = int(sec * SR)
    x = np.zeros(n)
    for _ in range(int(density * sec)):
        i = RNG.integers(0, n - 400)
        k = int(RNG.uniform(0.3, 1.0) * tail * SR) + 8
        x[i:i + k] += RNG.choice([-1, 1]) * RNG.uniform(0.3, 1.0) * np.exp(-np.arange(k) / (k / 4))
    hiss = bandnoise(n, lo, hi) * 0.18
    return x + hiss


def tone(sec, f, harm=(1.0, 0.35, 0.12), a=0.01, r=0.4, vib=0.0):
    t = t_(sec)
    ph = 2 * np.pi * f * t + (vib * np.sin(2 * np.pi * 5.2 * t) if vib else 0)
    x = sum(h * np.sin((i + 1) * ph) for i, h in enumerate(harm))
    return x * env(len(t), a, r) * np.exp(-t * 1.2)


def bell(sec, f):
    """A small lamp-like bell: FM, a bright attack that settles."""
    t = t_(sec)
    idx = 2.2 * np.exp(-t * 5)
    x = np.sin(2 * np.pi * f * t + idx * np.sin(2 * np.pi * f * 1.41 * t))
    return x * np.exp(-t * 2.4) * env(len(t), 0.002, 0.3)


def sweep(sec, f0, f1, curve=2.0):
    t = t_(sec)
    k = (t / t[-1]) ** curve
    f = f0 + (f1 - f0) * k
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph)


def hum(sec, f=55.0):
    t = t_(sec)
    x = np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * 2 * f * t) + 0.18 * np.sin(2 * np.pi * 3 * f * t)
    return x * (0.85 + 0.15 * np.sin(2 * np.pi * 0.7 * t))


def place(dst, src, at, gain=1.0):
    i = int(at * SR)
    j = min(len(dst), i + len(src))
    dst[i:j] += src[:j - i] * gain
    return dst


def stereo(x, width=0.0):
    """Mono to stereo with a few ms of offset for a little width."""
    d = int(width * SR)
    left = x
    right = np.concatenate([np.zeros(d), x[:len(x) - d]]) if d else x
    return np.stack([left, right], 1)


def finish(x, sec):
    n = int(sec * SR)
    x = x[:n] if x.ndim == 1 else x[:n]
    if x.ndim == 1:
        x = stereo(x, 0.0007)
    x = x * env(len(x), 0.004, 0.08)[:, None]
    rms = np.sqrt(np.mean(x ** 2)) + 1e-9
    x = x / rms * 10 ** (-18 / 20)                   # every sting about as loud: -18 dBFS RMS
    peak = np.abs(x).max()
    return np.tanh(x) / np.tanh(peak) * 0.89 if peak > 0.89 else x     # a soft knee: the peak lands at -1 dBFS


# ------------------------------------------------------------------ the stings
def crackle_in():
    """A set warming up: crackle rising, a squelch, then quiet. For takeovers and 'right back'."""
    sec = 1.1
    x = np.zeros(int(sec * SR))
    c = crackle(0.8, density=140) * np.linspace(0.2, 1.0, int(0.8 * SR))
    place(x, c, 0.0, 0.7)
    sq = bandnoise(int(0.18 * SR), 1500, 4500) * np.exp(-np.arange(int(0.18 * SR)) / (0.05 * SR))
    place(x, sq, 0.78, 0.9)
    place(x, tone(0.3, 1320, (1, .2), 0.003, 0.2), 0.8, 0.25)
    return finish(x, sec)


def dial_tune():
    """A dial swept across the band: a heterodyne whistle gliding down and locking onto a clean tone."""
    sec = 1.4
    x = np.zeros(int(sec * SR))
    w = sweep(0.9, 2600, 720, 0.6) * np.linspace(0.3, 0.8, int(0.9 * SR))
    place(x, w, 0.0, 0.35)
    place(x, crackle(0.9, density=90) * np.linspace(1, 0.2, int(0.9 * SR)), 0.0, 0.6)
    lock = tone(0.5, 720, (1, .25, .08), 0.004, 0.3)
    place(x, lock, 0.88, 0.55)
    return finish(x, sec)


def still_lit():
    """The night block's ident: a warm hum swells, a lamp's bell answers, a breath of crackle."""
    sec = 2.2
    x = np.zeros(int(sec * SR))
    h = hum(2.2, 55.0) * np.concatenate([np.linspace(0, 1, int(0.7 * SR)), np.linspace(1, 0.0, int(1.5 * SR))])
    place(x, h, 0.0, 0.35)
    place(x, bell(1.6, 659.25), 0.55, 0.6)           # E5
    place(x, bell(1.4, 987.77), 0.85, 0.32)          # B5, a fifth above
    place(x, crackle(0.5, density=40) * np.linspace(1, 0, int(0.5 * SR)), 1.6, 0.25)
    return finish(x, sec)


def spark():
    """A welder's spit: three short zaps, bright and dry. For LINEMAN."""
    sec = 0.8
    x = np.zeros(int(sec * SR))
    for at, g in ((0.0, 1.0), (0.17, 0.7), (0.31, 0.85)):
        n = int(0.12 * SR)
        z = bandnoise(n, 2500, 11000) * np.exp(-np.arange(n) / (0.025 * SR))
        z += 0.4 * sweep(0.12, 5200, 1800, 1.0)[:n] * np.exp(-np.arange(n) / (0.02 * SR))
        place(x, z, at, g)
    place(x, crackle(0.5, density=60, lo=3000, hi=12000) * np.linspace(1, 0, int(0.5 * SR)), 0.35, 0.35)
    return finish(x, sec)


def power_down():
    """Signing off: a tone falls away into a low hum that fades. For the night block's close."""
    sec = 1.8
    x = np.zeros(int(sec * SR))
    n = int(1.2 * SR)
    place(x, sweep(1.2, 520, 70, 0.7) * np.exp(-np.arange(n) / (0.6 * SR)), 0.0, 0.5)
    place(x, hum(1.8, 50.0) * np.linspace(0.8, 0.0, int(1.8 * SR)), 0.0, 0.3)
    place(x, crackle(0.4, density=30) * np.linspace(0.6, 0, int(0.4 * SR)), 1.1, 0.2)
    return finish(x, sec)


def signal_in():
    """A packet arriving: a quick digital chirp run, then a boot tone. For the takeover."""
    sec = 1.2
    x = np.zeros(int(sec * SR))
    for k in range(7):
        f = 900 * (1.19 ** k)
        n = int(0.05 * SR)
        place(x, np.sign(np.sin(2 * np.pi * f * t_(0.05))) * 0.4 * env(n, 0.002, 0.01), 0.04 * k, 0.5)
    place(x, crackle(0.35, density=150), 0.0, 0.4)
    place(x, tone(0.7, 440, (1, .5, .25), 0.01, 0.4), 0.36, 0.55)
    place(x, tone(0.6, 880, (1, .2), 0.01, 0.4), 0.42, 0.25)
    return finish(x, sec)


STINGS = {"crackle-in": crackle_in, "dial-tune": dial_tune, "still-lit": still_lit, "spark": spark,
          "power-down": power_down, "signal-in": signal_in}


def write(path, x):
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


if __name__ == "__main__":
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    for name, fn in STINGS.items():
        wav = os.path.join(out, name + ".wav")
        write(wav, fn())
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-c:a", "libopus", "-b:a", "96k",
                        os.path.join(out, name + ".ogg")], check=True)
        print(name, os.path.getsize(os.path.join(out, name + ".ogg")))

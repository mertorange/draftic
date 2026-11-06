"""Render the draft's pick sounds into frontend/sounds/, all on one glassy bell-pad instrument:

  pick-chime.wav  the "on the clock" jingle, played as each team's turn starts
  pick-good.wav   a quick rising fifth, for a pick that fits
  pick-bad.wav    a muffled falling tritone, for a wrong pick or the shot clock running out

The instrument: each note stacks octave partials (1x, 2x, 4x, 8x, 16x) with a few fast-fading
metallic overtones and a bright strike, rings until the next note damps it (the last rings
out), and is spread wide in stereo by detuned voices. The melodies are our own. Rendered
offline once so the browser only plays plain audio files.
Re-run after changing a recipe:  python backend/scripts/make_pick_sounds.py
"""

import wave
from pathlib import Path

import numpy as np

RATE = 44100
LENGTH = 2.9  # seconds: the longest sound, tail included (shorter ones are trimmed)
SOUNDS = Path(__file__).resolve().parents[2] / "frontend" / "sounds"

rng = np.random.default_rng(7)  # fixed seed: the same file on every render
t = np.arange(int(RATE * LENGTH)) / RATE

# (ratio to the note, level, decay in seconds). Octaves carry the tone and ring long; the
# odd ratios are the metallic glint that's gone within a few tenths of a second.
OCTAVES = [(1, 1.0, 1.6), (2, 0.72, 1.5), (4, 0.85, 1.0), (8, 0.26, 1.4), (16, 0.95, 0.3), (32, 0.15, 0.12)]
METAL = [(9.86, 0.3, 0.35), (19.7, 0.2, 0.2), (23.4, 0.25, 0.06)]
ATTACK = 0.015
RELEASE = 0.07   # how fast a note is damped once the next one starts
LEGATO = 0.03    # and how long it overlaps the next note before that, like a pianist's hand-off
VOICES = [(-0.0025, 0.9, 0.2), (0.0, 0.6, 0.6), (0.0025, 0.2, 0.9)]  # (detune, left, right)


def env(start, attack, decay):
    """0 before start, a quick rise, then an exponential fall."""
    x = t - start
    rise = np.clip(x / attack, 0, 1)
    return np.where(x < 0, 0.0, rise * np.exp(-np.clip(x, 0, None) / decay))


def note(freq, start, gain=1.0, end=None, bright=1.0):
    """One bell-pad note as a (left, right) pair. With an end, it's damped from there on (gone
    within ~0.1 s), so it doesn't ring on under the next note. A lower bright dulls everything
    above the octave (and drops the metallic glint at 0), for a muffled tone."""
    left, right = np.zeros_like(t), np.zeros_like(t)
    x = np.clip(t - start, 0, None)
    for ratio, level, decay in OCTAVES + METAL:
        f = freq * ratio
        if ratio > 2:
            level *= bright
        if f > RATE / 2 - 1000 or level == 0:
            continue
        shape = env(start, ATTACK if decay > 0.1 else 0.003, decay)
        for detune, l, r in VOICES:
            tone = np.sin(2 * np.pi * f * (1 + detune) * x + rng.uniform(0, 2 * np.pi))
            left += l * level * tone * shape
            right += r * level * tone * shape
    if end is not None:
        damp = np.where(t < end, 1.0, np.exp(-np.clip(t - end, 0, None) / RELEASE))
        left, right = left * damp, right * damp
    return gain * left, gain * right


def reverb(dry, seconds, mix):
    """Convolve with decaying, gently darkened noise: a big room. Each channel gets its own."""
    n = int(RATE * seconds)
    ir = rng.standard_normal(n) * np.exp(-np.arange(n) / (RATE * seconds / 6))
    ir = np.convolve(ir, np.ones(6) / 6, mode="same")
    ir /= np.sqrt(np.sum(ir ** 2))
    size = 1 << int(np.ceil(np.log2(len(dry) + n)))
    wet = np.fft.irfft(np.fft.rfft(dry, size) * np.fft.rfft(ir, size), size)[: len(dry)]
    return (1 - mix) * dry + mix * wet


# The melody as a tick pattern: each letter is a note struck on a tick, each "-" a tick of
# waiting; spaces and "|" are only there to read it. The held notes are the dashes.
PATTERN = "D-F-G-A---- | GEF-- C--A"
TICK = 0.08  # seconds per tick
PITCH = {"D": 293.66, "E": 329.63, "F": 349.23, "G": 392.00, "A": 440.00, "C": 523.25}  # D4..A4, C5
ACCENT = {"C": 1.0, "A": 1.0, "D": 1.0}  # the opening, held and high notes lead; the rest 0.85


def parse(pattern):
    """'D-F--A' -> [(freq, start, accent), ...]"""
    notes, tick = [], 0
    for ch in pattern:
        if ch in PITCH:
            notes.append((PITCH[ch], tick * TICK, ACCENT.get(ch, 0.85)))
            tick += 1
        elif ch == "-":
            tick += 1
    return notes


def render(notes, out, length=LENGTH, bright=1.0):
    """notes: [(freq, start, accent), ...] -> a stereo WAV of the given length."""
    left, right = np.zeros_like(t), np.zeros_like(t)
    for k, (freq, start, accent) in enumerate(notes):
        end = notes[k + 1][1] + LEGATO if k + 1 < len(notes) else None  # only the last rings free
        l, r = note(freq, start, gain=accent, end=end, bright=bright)
        left += l
        right += r

    left, right = reverb(left, 1.3, 0.28), reverb(right, 1.3, 0.28)
    mix = np.stack([left, right], axis=1)[: int(length * RATE)]

    # Fade the very ends so nothing clicks, then normalize to -1 dBFS.
    fade_in, fade_out = int(0.003 * RATE), int(min(0.7, length / 3) * RATE)
    mix[:fade_in] *= np.linspace(0, 1, fade_in)[:, None]
    mix[-fade_out:] *= (np.linspace(1, 0, fade_out) ** 2)[:, None]
    mix *= 10 ** (-1 / 20) / np.max(np.abs(mix))

    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes((mix * 32767).astype("<i2").tobytes())
    print(f"wrote {out.name} ({out.stat().st_size // 1024} KB, {length}s)")


B3, A4, E5 = 246.94, 440.00, 659.25

if __name__ == "__main__":
    render(parse(PATTERN), SOUNDS / "pick-chime.wav")
    # Correct: a quick, bright rising fifth that rings briefly
    render([(A4, 0.0, 0.85), (E5, 0.09, 1.0)], SOUNDS / "pick-good.wav", length=1.1)
    # Wrong: a falling tritone, muffled, so it reads as a miss without being harsh
    render([(PITCH["F"], 0.0, 0.9), (B3, 0.13, 1.0)], SOUNDS / "pick-bad.wav", length=1.0, bright=0.2)

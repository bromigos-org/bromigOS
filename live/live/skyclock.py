"""The real sky, computed locally (no network): the time of day as a light grade, the
moon's phase and place, and a tide from the moon.

All of it is arithmetic on the local clock:
  phase()        the moon's age as a fraction of the synodic month (0 new, 0.5 full),
                 from a known new moon (2000-01-06 18:14 UTC); good to well under a day.
  daylight()     0 at night, 1 by day, with dawn and dusk ramps at the world's hours.
  grade()        (r, g, b multiplier, warm glow) for the hour: night, dawn, day, dusk.
  moon_place()   where the moon sits in the sky window for the hour (0..1 across, 0..1 up).
  tide()         -1 low .. +1 high: semi-diurnal, following the moon's hour angle, with
                 spring tides at new and full moon and neaps at the quarters.
"""
import math
import time

SYNODIC = 29.530588853
NEW_MOON_2000 = 947182440.0          # 2000-01-06 18:14 UTC, epoch seconds


def local_hour(now=None):
    lt = time.localtime(now)
    return lt.tm_hour + lt.tm_min / 60.0 + lt.tm_sec / 3600.0


def phase(now=None):
    """The moon's age, 0..1 (0 new, 0.25 first quarter, 0.5 full, 0.75 last quarter)."""
    t = time.time() if now is None else now
    return ((t - NEW_MOON_2000) / 86400.0 / SYNODIC) % 1.0


def illumination(ph):
    """Lit fraction of the disc for a phase."""
    return 0.5 * (1.0 - math.cos(2 * math.pi * ph))


def _ramp(h, a, b):
    if b <= a:
        return 1.0 if h >= a else 0.0
    return max(0.0, min(1.0, (h - a) / (b - a)))


def daylight(hour, dawn=(5.5, 7.5), dusk=(18.0, 20.5)):
    """0 night .. 1 day, ramping through dawn and dusk."""
    if hour < dawn[0] or hour >= dusk[1]:
        return 0.0
    if hour < dawn[1]:
        return _ramp(hour, *dawn)
    if hour < dusk[0]:
        return 1.0
    return 1.0 - _ramp(hour, *dusk)


def twilight(hour, dawn=(5.5, 7.5), dusk=(18.0, 20.5)):
    """How much of a warm twilight glow is in the sky: peaks mid-dawn and mid-dusk."""
    out = 0.0
    for a, b in (dawn, dusk):
        mid, half = (a + b) / 2.0, max((b - a) / 2.0 + 0.6, 0.1)
        out = max(out, max(0.0, 1.0 - abs(hour - mid) / half))
    return out


def _mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def grade(hour, g):
    """The world's light for the hour. g: the world's [clock] table with rgb triples for
    night, dawn, day and dusk (multipliers on the art), and the dawn/dusk hours.
    Returns (r, g, b, twilight 0..1)."""
    dawn, dusk = tuple(g.get("dawn", (5.5, 7.5))), tuple(g.get("dusk", (18.0, 20.5)))
    night, day = g["night"], g["day"]
    tw = twilight(hour, dawn, dusk)
    base = _mix(night, day, daylight(hour, dawn, dusk))
    warm = g["dawn_tint"] if hour < 12.0 else g["dusk_tint"]
    c = _mix(base, warm, tw * 0.75)
    return (c[0], c[1], c[2], tw)


def moon_place(hour, ph):
    """(x 0..1 left to right, y 0..1 up) for the moon in the sky window. The moon transits
    about ph * 24.8 h after the sun: new moon rides with the sun, full moon at midnight."""
    transit = (12.0 + ph * 24.8) % 24.0
    ha = ((hour - transit + 12.0) % 24.0) - 12.0          # hours from transit, -12..12
    x = 0.5 + ha / 12.0                                   # rises left (east), sets right
    y = math.cos(ha / 12.0 * math.pi * 0.5 * 1.6)        # 1 at transit, below 0 about 7.5 h out
    return x, y


def tide(hour, ph):
    """-1 low .. +1 high, two highs a day following the moon, springs at new and full."""
    transit = (12.0 + ph * 24.8) % 24.0
    ha = (hour - transit) / 24.84 * 2 * math.pi           # lunar hour angle, radians
    spring = 0.65 + 0.35 * math.cos(4 * math.pi * ph)     # 1 at new/full, 0.3 at the quarters
    return math.cos(2 * ha) * spring

"""Reduced motion (docs/accessibility.md): how much the live layer moves.

The setting is the user's `motion` in ~/.config/bromigos/accessibility.toml (`bromigos
accessibility motion full|reduced|still`), merged into the config as `general.motion` by
config.py; the old `general.reduced_motion = true` still means at least "reduced".

  full     everything moves as designed.
  reduced  calm: the worlds keep their look and their life, slower (RATE), with no
           parallax, no flicker or blinking (lights hold steady), no flashes (lightning,
           the den's static bursts, the workspace wipe, rain bursts), no rotation (the
           burn-in, the den's relay map), no craft crossing the sky; the unlock/login
           intercept crossfades instead of tearing; a scan fades the schematic in instead of
           sweeping a beam; decks don't drift when left alone.
  still    all of reduced, and the background holds a still frame: the scene's clock
           stands, and the picture is drawn again only when what it shows changes (an
           agent's state, the weather's level, the hour, the lab's health) or once a
           minute (STILL_EVERY). Each new frame is a cut: the scene's time moves on by
           STILL_STEP first, so a creature that rose or went under is drawn where it ended.
           Video loops hold a frame; one-off creatures (event actors) aren't spawned.

Renderers keep their own Clock: real seconds in, the scene's seconds out.
"""

MODES = ("full", "reduced", "still")
RATE = {"full": 1.0, "reduced": 0.4, "still": 0.0}
STILL_STEP = 6.0       # seconds of the scene's time a still frame moves on by (transitions settle)
STILL_SUB = 0.1        # in steps of this (the worlds' simulation step)
STILL_EVERY = 60.0     # seconds between still frames when nothing changes (the clock, the sky)
STILL_CHECK = 2.0      # how often the app asks whether the picture changed

# The mode in force in this process (App sets it on every config load; offscreen.py too).
# For code that has no config at hand (glkit's text reveal flash).
CURRENT = "full"


def mode(cfg):
    """The motion mode a config says: general.motion, else the legacy reduced_motion."""
    g = (cfg or {}).get("general", {}) or {}
    m = str(g.get("motion") or "full")
    if m not in MODES:
        m = "full"
    if m == "full" and g.get("reduced_motion"):
        m = "reduced"
    return m


def calm(cfg_or_mode):
    """Anything but full motion: no parallax, flicker, flashes or rotation."""
    m = cfg_or_mode if isinstance(cfg_or_mode, str) else mode(cfg_or_mode)
    return m != "full"


def calm_now():
    return CURRENT != "full"


def set_current(m):
    global CURRENT
    CURRENT = m if m in MODES else "full"


class Clock:
    """A renderer's animation clock. Call it with the renderer's real seconds (its now());
    it returns the scene's seconds: the same in full, RATE times slower in reduced, standing
    in still (where step() moves it on, for a new still frame)."""

    def __init__(self, m="full"):
        self.mode = m if m in MODES else "full"
        self.rate = RATE[self.mode]
        self.t = 0.0
        self.last = None

    def __call__(self, real):
        if self.rate == 1.0:                 # full: the renderer's own seconds, exactly
            self.last = self.t = real
            return real
        if self.last is None:
            self.last = real
            self.t = real * self.rate if self.rate else 0.0
        d = max(0.0, real - self.last)
        self.last = real
        self.t += d * self.rate
        return self.t

    def peek(self, real):
        """The scene's time at `real`, without moving the clock (for events stamped between
        frames)."""
        if self.rate == 1.0:
            return real
        if self.last is None:
            return real * self.rate
        return self.t + max(0.0, real - self.last) * self.rate

    def step(self, seconds):
        """Still: jump the scene's time forward (the caller simulates the gap)."""
        self.t += seconds
        return self.t


def still_steps(seconds=STILL_STEP, sub=STILL_SUB):
    """The sub-steps a still frame's jump is simulated in: [(offset, dt), ...]."""
    n = max(1, int(round(seconds / sub)))
    return [((i + 1) * sub - seconds, sub) for i in range(n)]

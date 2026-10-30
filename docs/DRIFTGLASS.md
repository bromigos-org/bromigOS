# DRIFTGLASS

DRIFTGLASS is the design language shared by bromigOS, BRODEC and the Bromigos
sites. In the canon, Earth only receives: everything on a screen is signal
coming in from the Drift, shown on glass. These are the words we use to talk
about it, so "make it more GLOW" or "that's FLARE, it should be EMBER" means
the same thing to everyone.

This is the vocabulary. The detailed tokens live with each product: bromigOS
themes ([theming.md](theming.md)), BRODEC's `DESIGN.md`.

## The three levels

Every surface sits at one level. The level decides how much light and motion
it may use.

| Level | Where | What it may do |
|---|---|---|
| **EMBER** | Bar and tray icons, status text, dense or text-heavy screens | No running motion. Colour and state only, plus a single short **Spark** when something changes. |
| **GLOW** | Pop-ups, panels, cards, settings pages, TUIs | Holograms and motion **inside the panel only**, and only in response to state (scanning, connecting, playing). Opens instantly. |
| **FLARE** | Hero moments: VECTOR's hologram, the FIELD OPS table, world wallpapers, the stage | Full effect. **One FLARE per screen.** |

Examples: the Bluetooth tray icon is EMBER; its pop-up is GLOW. VECTOR's
talking hologram is FLARE.

## The building blocks

- **Glass**: the translucent panel surface, in the world's colours.
- **Emitter**: the glowing base a hologram stands on.
- **Scanline**: the faint horizontal lines over glass and holograms.
- **Sweep**: the radar scan, shown while searching (devices, contacts, signal).
- **Pulse**: a slow breath while waiting or connecting.
- **Spark**: a one-time glow (about a second) when something succeeds or
  changes, then still.
- **Reading**: the rule that a glow always means something (a state, a level,
  a signal). Never decoration.
- **Hero**: the one FLARE element a screen may have.

## Rules

1. **Readable first.** Plain labels and obvious controls; DRIFTGLASS is
   layered on top, never instead.
2. **Instant.** Nothing makes you wait for an animation: panels open in about
   120 ms or less, and motion never blocks input.
3. **Reduced motion** (`bromigos accessibility motion reduced`) turns every
   Pulse, Sweep, Spark and FLARE animation off; high contrast is respected.
4. **Every world.** It must read well in every world theme, the Wick included.
5. **Calm by default.** Nothing animates on the desktop or over other windows
   unless the user is looking at that surface.

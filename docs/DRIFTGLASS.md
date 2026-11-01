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

### bromigOS Server's screens

The Server path in the installers and the server's first-start tour use the same blocks
around one recurring hologram: **the rack**, the vector gallery's own render, turning on its
Emitter (`desktop/art/server-rack.png`, 24 frames; `lib/bromigos_rack.py`, the same frames as
braille for the terminal; both made by `tools/installer-art/make.py rack`). Each step's hero
stands on a holo-table: Glass with the table's glow, a floor grid drifting toward you, the
Scanline passing down and lit corner brackets. The rack is this server in every picture: on
the network, with the way in seated on its front, taking its roles (each a module that lights
with a Spark), and while installing, a Sweep rises up it to the height done. The cards are
hologram tiles (a Scanline texture, the Emitter's light from the top). In the terminal the
rack turns beside each step's picture, lit by brightness with a Sweep row; the Linux console
and ASCII get a drawn rack with the same Sweep, and reduced motion holds one frame.

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

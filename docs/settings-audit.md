# The Settings audit, October 2026

This is a historical record. On 2026-10-09, before the Settings window was overhauled,
every page was rendered offscreen and checked against what a modern desktop's settings
offer. This page lists what was broken, unclear or missing, and what the overhaul did
about each. The window as it is now is described in [settings.md](settings.md).

## How the audit was done

- Every page was opened offscreen with `tools/settings/render.sh`, in a headless weston
  with a throwaway home.
- Each page was drawn in three themes: the Wick, Mire and Tidewell.
- Each was drawn at 1120×780, and at 1366×738, 1920×1080 and 640×720.
- The pages were compared with GNOME Settings, KDE System Settings and macOS System
  Settings, then mapped onto what bromigOS can actually control.

## The window

### The sidebar

- **Before:** one flat list of six pages, with no groups.
- **After:** the pages are grouped under System, Desktop, VECTOR & AI, Lab, Personal and
  About.

### Search

- **Before:** "Search pages" matched only a page's title, summary and keywords. No single
  setting could be found. "repeat rate", "dark" and "wifi" found nothing.
- **After:** every control is indexed by its name, its synonyms and its page. A result
  opens the page on that row and highlights it.

### The page layout

- **Before:** the header repeated the sidebar's summary, and nothing explained the page.
  Rows had their buttons at the end. A few rows were read-only text that looked like
  controls.
- **After:** a header with the title, a short explanation and Reset to defaults. Then
  groups of rows, each with a label, a hint line and its control.

### Hover hints

- **Before:** most controls had one. The theme's swatches said only `role #hex`, and
  read-only rows had none.
- **After:** every control has one, and a test walks every page's widgets to check.

### Undo

- **Before:** Idle & lock, Accessibility and Shortcuts offered Undo. No other page could
  change anything.
- **After:** every change applies at once and offers Undo, and Ctrl+Z undoes the last one.

### Reset to defaults

- **Before:** only Shortcuts had it, as Reset….
- **After:** it's in every page's header. Where nothing has a bromigOS default, such as a
  Wi-Fi network or a paired device, the button says so instead.

### Where a setting is written

- **Before:** no page said. Idle & lock listed its files at the bottom.
- **After:** every row has an Advanced line that names the file and key it writes and the
  command it runs.

### The keyboard

- **Before:** arrows and Tab moved through the sidebar. There was no way to search without
  the mouse, and no shortcut to switch pages.
- **After:**
  - Type anywhere, or press Ctrl+F, to search. Esc clears it, and Enter opens the first
    result on its row.
  - Ctrl+PgUp and Ctrl+PgDn move between pages.
  - Ctrl+1 to Ctrl+6 open the groups. Alt and digits stay Hyprland's workspace keys.
  - Ctrl+Z undoes, and F1 opens the page's part of the manual.
  - All of it was proved with a virtual keyboard in a nested Hyprland.

### Theme changes

- **Before:** the window restyled within two seconds, except colours set per widget, such
  as the swatches.
- **After:** the same check runs, plus a watch on `palette.json`. Pages that draw, such as
  the displays' arrangement and the panels' layout, read the colours in force at each
  draw. `ctx.on_restyle` tells a page when they change.

### Small screens

- **Before:** the window opened at 1120×780, taller than a 1366×768 screen under the bar.
  At 640 px wide it never collapsed, because the compositor refused its size.
- **After:**
  - The window is sized to the monitor: 85% of it, at most 1280×860.
  - Below 720 px wide, the sidebar and the page show one at a time, with a back button.
  - A row's buttons wrap, and sliders and dropdowns shrink.
  - The audit fails a row wider than the window at 640 px.

### Large screens

- **Before:** the content was clamped at 880 px, which was fine, but sliders were 250 px.
- **After:** the content is clamped at 1000 px, and sliders grow with their row.

### A failed read

- **Before:** Shortcuts showed no keys and no reason when `bromigos keys` answered empty.
  Creation targets said "nothing answers now", with the reason only in the hover.
- **After:** every failed read is an error row showing the command and what it said.

## The pages that existed

### Idle & lock

- **Before:** a "Custom/Default" row under the presets repeated the toggle. The files sat
  in a group at the bottom.
- **After:** the same controls and behaviour in the new layout. The files moved into each
  row's Advanced line.

### Theme

- **Before:** read-only, with swatches that had no names.
- **After:** rebuilt separately, alongside the theme switcher, as the page that wears a
  theme with a click. The audit left it alone.

### Shortcuts

- **Before:** complete, but it said nothing when the list was empty.
- **After:** the same, in the new layout. An empty list says why.

### Accessibility

- **Before:** complete.
- **After:** the same, in the new layout.

### Creation targets

- **Before:** read-only. It showed raw ids such as `model3d.generate`. It had no probe and
  no choice per service, and the reason a service didn't answer was only in the hover.
- **After:** each service can put the homelab, this machine or the cloud first
  (`bromigos target … --only`). The probe's results are shown, with Probe now.

### Updates

- **Before:** the channel was read-only, and the page said "1 upgrade(s)". The package
  list was only in a hover. Nothing covered snapshots, rollback or the boot menu, and the
  last update wasn't shown.
- **After:** the page became Updates & recovery.
  - The channel can be switched, in a terminal, because it needs sudo.
  - Update now opens a terminal running `bromigos update`.
  - What's waiting is listed, and the last update is shown.
  - Snapshots and rollback come from `bromigos rollback status`.
  - The boot menu's theme appears once `bromigos boot` is installed.

## What was missing

Each line is something a desktop's settings are expected to have. It says what bromigOS
controls it through, and the page that now covers it.

| Expected | Controlled through | Before | Now |
|---|---|---|---|
| Displays | Hyprland, the `bromigos setup monitors` block | a terminal only | Displays (`bromigos display`) |
| Sound | PipeWire, the live layer's sounds, `bromigos mute` | the bar opened pavucontrol | Sound (`bromigos sound`) |
| Network | NetworkManager | the CONNECTIONS panel, nmtui | Network (`bromigos net`) |
| Bluetooth | bluez | nothing | Bluetooth (`bromigos bluetooth`) |
| Power | power-profiles-daemon, sysfs, logind, `idle.toml` | the bar's profile button | Power (`bromigos power`) |
| Keyboard, mouse, touchpad | Hyprland's input block | `bromigos setup input` in rofi | Keyboard & input |
| Peripherals | `bromigos peripheral` | a terminal | Peripherals |
| Notifications | dunst | nothing | Notifications (`bromigos notifications`) |
| Default apps | xdg-mime, `bromigos.apps`, web apps | nothing | Default apps (`bromigos defaults`) |
| Startup apps | `bromigos.autostart`, `bromigos windows` | nothing | Startup (`bromigos startup`) |
| Date and time | timedated, the bar's clock | nothing | Date & time (`bromigos clock`) |
| The assistant | VECTOR's settings and files | nothing | VECTOR |
| Wallpaper and screensaver | the live layer, the world | the animation list in a terminal | Live layer & holograms |
| Widgets | `layout.json`, `weather.toml` | nothing | Widgets (`bromigos panels`) |
| Extensions | `bromigos ext` | nothing | Extensions |
| Users | `profile.toml`, the private overlay, `~/.face` | nothing | Account |
| About | `bromigos --version`, pacman, `bromigos hw` | nothing | About (`bromigos about`) |

Some details behind those rows:

- **Displays** now covers each output's mode, refresh rate, scale, position, primary and
  on/off. You drag the outputs to arrange them. Changes apply the safe way, with a
  15-second "Keep these settings?" that reverts by itself.
- **The assistant.** GNOME has none. macOS has Siri, and Windows has Copilot. The VECTOR
  page covers his brain, voice, conversation, keys, memory and history, and his
  emergency switch.

## Out of scope, and why

- **Printers.** No print stack ships.
- **Region and language.** The installer sets the locale, and there's no runtime switch
  yet.
- **Online accounts and sharing.** Nothing in bromigOS uses them.
- **Privacy beyond VECTOR's own data.** The desktop portal asks per app.

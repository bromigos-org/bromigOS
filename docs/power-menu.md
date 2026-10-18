# Keyboard power menu

`bin/bromigos-power-menu` exposes `bromigos power menu` through the core command
router. `lib/bromigos_power_menu.py` uses Python's standard `curses` module.
The manual has [user instructions](../manual/src/power-menu.md).

The menu separates key handling, drawing and execution. A new menu selects Cancel;
each confirmation also starts at Cancel. Escape backs out. Arrows, Enter, j/k/h/l
and Tab work without a mouse. A small terminal displays a size hint and ignores
action keys. ASCII text and basic colours work on Linux virtual consoles.

`curses.wrapper` restores the terminal before execution. An accepted choice runs
`systemctl --no-ask-password` with exactly one of `suspend`, `reboot` or `poweroff`.
It does not escalate, force an action or bypass system inhibitors. Command failures
remain visible and return a failing exit status. `--preview` takes the same input
path but never runs a power command.

Tests in `tests/console/test_power_menu.py` use offscreen grids and a fake command
runner. They cover confirmation defaults, keyboard controls, cancellation, narrow
layouts, resizing, preview and refused actions. Native curses was also exercised
through a disposable PTY with preview enabled and process execution disabled.

# __TITLE__

A desktop panel (widget) for bromigOS. Panels are the small dashboards that sit above
the animated background and below your windows. This one shows the machine's load
average on seven-segment digits.

## Edit it

`widget.py` defines a `panels.Panel` subclass:

- `tick()` takes a sample, every `interval` seconds.
- `draw()` paints with Cairo and the panels' drawing helpers, such as `D.frame`,
  `D.label`, `D.seg7`, `D.spark` and `D.ring`.
- `region()` gives each part of the panel its hover hint.

`LAYOUT` sets the panel's size. A user's `layout.json` can place it by name. bromigOS's
`docs/plugins.md` describes the rest.

## Try it

From the folder that holds this one:

```bash
bromigos ext validate ./__NAME__
bromigos ext install --copy ./__NAME__    # asks first; it appears within a few seconds
bromigos-widgets render __IDENT__ out.png # draws it offscreen
```

The panels look for changes every 2 seconds. An error shows in the panel itself and
never reaches the others. After each edit, run `bromigos ext update __NAME__` to copy
your folder in again.

## Publish it

Put this folder in a Git repository, push it, and tag a release:

```bash
git tag v0.1.0 && git push --tags
```

People then install it with `bromigos ext install <your repository's URL>@v0.1.0`. To
list it in the catalog, see "Publish an extension" in bromigOS's `docs/extensions.md`.

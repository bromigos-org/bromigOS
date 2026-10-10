# Make your own widget

A widget is one of the [panels](panels.md) on your desktop. You can make your own in a
few minutes: it's one small Python file inside an [extension](extensions.md), which is a
folder you can share as a git repository. This page takes you from nothing to a widget
other people can install.

You'll need to know a little Python. The developer docs have the details of every part:
[plugins.md](https://github.com/bromigos-org/bromigOS/blob/main/docs/plugins.md#add-a-panel)
for what a panel is made of, and
[widgets.md](https://github.com/bromigos-org/bromigOS/blob/main/docs/widgets.md#adding-a-widget)
for sizes and settings.

## 1. Start from a working widget

```bash
bromigos ext new widget my-gauge
```

This makes a folder, `my-gauge`, with a widget that already works: it shows the machine's
load average. The folder holds:

- `widget.py`, the widget itself;
- `bromigos-ext.toml`, the manifest, which says what the extension is and what it may do;
- `README.md`, for the people who'll use it.

## 2. Make it yours

Open `widget.py`. The widget is a class with a few parts:

- `tick()` reads your data. It runs every `interval` seconds.
- `draw(cr, w, h)` paints the panel, using the same drawing helpers as bromigOS's own
  panels, so it matches every theme.
- `region(x, y, w, h, "…")` gives each part a hover hint. Every part should have one.

Then tell the gallery about it. These lines are what people see on its card:

```python
    description = "The load average over 1, 5 and 15 minutes"
    category, reads = "system", "the load average"
```

`category` is one of `system`, `network`, `homelab`, `media`, `notes` or `fun`. `reads` says
in a few words what data it looks at.

Two more things make a widget feel at home:

- **Sizes.** A widget can have a compact size, a standard one, and wider or larger ones
  that show more. You list them in `sizes`, and draw each its own way. See
  [Size classes](https://github.com/bromigos-org/bromigOS/blob/main/docs/widgets.md#size-classes).
- **Settings.** If your widget needs a place, a list of hosts or a sign-in to an online
  account, list them in `settings`. bromigOS draws the form for you, and keeps any token
  in your keyring. See
  [A widget's settings](https://github.com/bromigos-org/bromigOS/blob/main/docs/widgets.md#a-widgets-settings).

Show real data only. If there's nothing to read, say so in the panel.

## 3. Try it

Check the folder the way installing would, then look at the widget without putting it on
your desktop:

```bash
bromigos ext validate ./my-gauge
bromigos-widgets render ./my-gauge/widget.py out.png                 # draw it to a picture
bromigos-widgets render ./my-gauge/widget.py big.png --size 900x600  # at another size
```

Open the pictures to see it. Nothing appears on your desktop yet.

When it looks right, install your folder:

```bash
bromigos ext install --copy ./my-gauge
```

A widget runs code, so this shows what it can do and asks you to type yes. Within a few
seconds the widget is in the widget gallery: press <kbd>Super</kbd>+<kbd>Alt</kbd>+<kbd>W</kbd>
and switch it on. After each change to your folder, run `bromigos ext update my-gauge` to
copy it in again.

## 4. Share it

Put the folder in a git repository and push it. Tag a version so people can pin it:

```bash
git tag v0.1.0 && git push --tags
```

Anyone can now install it by its link. They open **Settings › Widgets**, click **Install
from URL…** and paste it, or run:

```bash
bromigos ext install https://github.com/you/my-gauge@v0.1.0
```

Before installing, they see your widget's name, what it reads, its licence and what it may
reach.

## 5. Put it in the catalog

The catalog is the list that **Get more widgets** shows. To add your widget, open a pull
request to [bromigos-org/extensions](https://github.com/bromigos-org/extensions) with an
entry in its `index.toml` and a picture of your widget. That repository's
[CONTRIBUTING.md](https://github.com/bromigos-org/extensions/blob/main/CONTRIBUTING.md)
has the steps and what reviewers look for.

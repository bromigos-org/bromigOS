# __TITLE__

A deck for bromigOS. A deck is a full-screen holographic view that the live layer, the
program behind the animated background, draws over your windows. This one shows the
machine's load averages as three rings.

## Edit it

`deck.py` is the whole deck:

- `_sample()` reads the data. It runs on a separate thread, so it can take its time.
- `build()` draws the scene with deckkit's painter, using calls such as `b.arc`,
  `b.line` and `b.text`. `space=2` draws in the deck's 3D space.
- `pick_pts` and `pick_ids` make things hoverable and clickable.

Replace `_sample()` and `build()` with your own. The live layer's `live/deckkit.py` and
bromigOS's `docs/plugins.md` describe the rest.

In `bromigos-ext.toml`, list the hosts and paths your deck reaches under
`[permissions]`. People see them before they install.

## Try it

From the folder that holds this one:

```bash
bromigos ext validate ./__NAME__
bromigos ext install --copy ./__NAME__    # asks first, because a deck runs code
bromigos-live plugin __NAME__             # opens it; Esc closes it
```

The deck reloads when its file changes. After each edit, run `bromigos ext update
__NAME__` to copy your folder in again.

To draw it without a window, run this from a bromigOS checkout:

```bash
python live/tools/offscreen.py plugin:__NAME__ out.png 2
```

## Publish it

Put this folder in a Git repository, push it, and tag a release:

```bash
git tag v0.1.0 && git push --tags
```

People then install it with `bromigos ext install <your repository's URL>@v0.1.0`. To
list it in the catalog, see "Publish an extension" in bromigOS's `docs/extensions.md`.

# __TITLE__

A theme for bromigOS. A theme sets the colours of the whole desktop at once: the bar,
the terminal, notifications, the lock screen and every app bromigOS themes. This one
starts as teal on slate, ready for you to make your own.

## Edit it

- `colors.toml` holds the colour roles every app reads, such as `background`, `primary`
  and `text`. Start here.
- `theme.toml` holds the theme's name, description and mode.

You can add backgrounds, an emblem or a painted world later. bromigOS's
`docs/theming.md` describes each file.

## Try it

From the folder that holds this one:

```bash
bromigos ext validate ./__NAME__
bromigos theme previews --dir ./__NAME__ --out preview.jpg    # your desktop in it, drawn offscreen
bromigos ext install --copy ./__NAME__
bromigos theme set __NAME__
```

A theme installs without a question, because it's only data. After each edit, run
`bromigos ext update __NAME__` to copy your folder in again, then `bromigos theme set
__NAME__`.

## Publish it

Put this folder in a Git repository, push it, and tag a release so people can pin it:

```bash
git tag v0.1.0 && git push --tags
```

People then install it with `bromigos ext install <your repository's URL>@v0.1.0`. To
list it in the catalog, see "Publish an extension" in bromigOS's `docs/extensions.md`.

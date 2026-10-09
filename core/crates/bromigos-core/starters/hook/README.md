# __TITLE__

A theme-set hook for bromigOS. It runs after every `bromigos theme set`. This one writes
the theme's name and accent colour to
`~/.local/state/bromigos-ext/__NAME__/theme.txt`, where another script can read them.

## Edit it

`theme-set` is the hook. Use a hook for what a theme template can't do, such as
restarting an app or switching a gsetting. It gets:

- the theme's name as `$1`;
- `BROMIGOS_THEME`, the theme's name again;
- `BROMIGOS_THEME_DIR`, the rendered theme, with `palette.json` and every app's file.

Keep it quick: `bromigos theme set` waits for every hook.

It's linked as `__NAME__--theme-set`. A hook of the user's with that name, in
`~/.config/bromigos/hooks/theme-set.d/`, replaces it.

## Try it

From the folder that holds this one:

```bash
bromigos ext validate ./__NAME__
bromigos ext install --copy ./__NAME__    # asks first, because it runs code
bromigos theme set wick && cat ~/.local/state/bromigos-ext/__NAME__/theme.txt
```

You can also run the file directly. After each edit, run `bromigos ext update __NAME__`.
Keep the executable bit committed: `git update-index --chmod=+x theme-set`.

## Publish it

Put this folder in a Git repository, push it, and tag a release:

```bash
git tag v0.1.0 && git push --tags
```

People then install it with `bromigos ext install <your repository's URL>@v0.1.0`. To
list it in the catalog, see "Publish an extension" in bromigOS's `docs/extensions.md`.

# __TITLE__

A memory store for VECTOR, bromigOS's desktop AI assistant. It decides how he remembers
and recalls things. This one keeps notes in a JSON-lines file,
`~/.local/state/bromigos-ext/__NAME__/notes.jsonl`, and recalls them by shared words. It
needs no network and no embeddings.

## Edit it

`memory.py` registers the store in `register(vector)`. Its docstring lists the interface:
`recall`, `remember`, `forget`, `summarize` and a few helpers. `recall` is on the hot path,
so it must return within the time budget it's given. Swap in your own backend, such as a
database or a service. If it talks to a host, declare it under `[permissions]` in
`bromigos-ext.toml`.

## Choose which store VECTOR uses

`[memory] backend` in `~/.config/bromigos/vector/vector.toml` decides:

- `"auto"`, the default, uses the first store a plugin registers. Installing this one
  makes it his memory.
- `"local"` keeps his own SQLite store. Use it while you build yours.
- `"__IDENT__"` picks this one by name.

## Try it

From the folder that holds this one:

```bash
bromigos ext validate ./__NAME__
bromigos ext install --copy ./__NAME__    # asks first, because it runs code
bromigos restart vector
```

After each edit, run `bromigos ext update __NAME__` and `bromigos restart vector`. Don't
edit the installed copy. VECTOR's guard checks his plugin files against what
`bromigos ext` recorded, and logs a hand edit as unverified.

## Publish it

Put this folder in a Git repository, push it, and tag a release:

```bash
git tag v0.1.0 && git push --tags
```

People then install it with `bromigos ext install <your repository's URL>@v0.1.0`. To
list it in the catalog, see "Publish an extension" in bromigOS's `docs/extensions.md`.

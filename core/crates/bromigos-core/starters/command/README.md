# __TITLE__

A command for bromigOS. A file named `bromigos-<group>-<name>` runs as `bromigos <group>
<name>`, and `bromigos-<group>` runs as `bromigos <group>`. This one,
`bromigos-__NAME__`, says hello and names the theme in use.

## Edit it

`bromigos-__NAME__` is a Bash script, but any executable works, a binary too. To change
how it's typed, rename the file and change `path` under `[[provides]]` in
`bromigos-ext.toml` to match.

Its first comment block is its header. bromigOS reads these lines:

- `# bromigos:summary=` is the one-line description that `bromigos commands` and the menu
  show.
- `# bromigos:args=` and `# bromigos:examples=` document how to call it.
- `# bromigos:hidden=true` keeps it out of the lists.
- `# bromigos:menu=GROUP:Label` puts it in the menu (Super+Space).
- `# bromigos:prompt=WHAT` makes the menu ask for one argument first.

Keep the executable bit committed: `git update-index --chmod=+x bromigos-__NAME__`.

## Try it

From the folder that holds this one:

```bash
bromigos ext validate ./__NAME__
bromigos ext install --copy ./__NAME__    # asks first, because it runs code
bromigos commands | grep __NAME__         # the command router finds it
```

You can also run the file directly. After each edit, run `bromigos ext update __NAME__`.

## Publish it

Put this folder in a Git repository, push it, and tag a release:

```bash
git tag v0.1.0 && git push --tags
```

People then install it with `bromigos ext install <your repository's URL>@v0.1.0`. To
list it in the catalog, see "Publish an extension" in bromigOS's `docs/extensions.md`.

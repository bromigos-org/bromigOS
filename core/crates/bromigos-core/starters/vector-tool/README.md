# __TITLE__

A tool for VECTOR, bromigOS's desktop AI assistant. VECTOR decides when to call a tool
from its description. This one, `__IDENT___uptime`, tells him how long the machine has
been up and how loaded it is.

## Edit it

`tool.py` adds tools in `register(vector)`:

```python
vector.tool(name, description, json_schema, fn, level="read")
```

- `name` is lower_snake_case, 3 to 40 characters.
- `description` is what VECTOR reads to decide when to use it. Write it for him.
- `json_schema` describes the tool's arguments.
- `level` is `"read"` for a tool that looks things up, or `"desktop"` for one that changes
  this desktop. An extension never gets VECTOR's terminal.

Declare the level as `vector` under `[permissions]` in `bromigos-ext.toml`, with the hosts
and paths the tool reaches. People see them before they install.

## Try it

From the folder that holds this one:

```bash
bromigos ext validate ./__NAME__
bromigos ext install --copy ./__NAME__    # asks first, because it runs code
bromigos restart vector                   # he loads plugins when he starts
```

Then ask VECTOR how long the machine has been up.

Installed tools are protected like his own. If you edit the installed copy by hand, his
terminal switches off. Edit this folder instead, then run `bromigos ext update __NAME__`
and `bromigos restart vector`.

## Publish it

Put this folder in a Git repository, push it, and tag a release:

```bash
git tag v0.1.0 && git push --tags
```

People then install it with `bromigos ext install <your repository's URL>@v0.1.0`. To
list it in the catalog, see "Publish an extension" in bromigOS's `docs/extensions.md`.

# __TITLE__

A homelab adapter for bromigOS. An adapter talks to one kind of service and provides
*capabilities*, such as hosts, metrics or workloads. The desktop's panels, `bromigos lab`
and VECTOR's homelab tools then show what it provides. This one needs no service: it
reports this machine as a host.

## Edit it

`adapter.py` defines a `registry.Adapter` subclass, registered with `@register` under its
`type`. It lists the capabilities it offers in `provides`, and has one method for each.
`bromigos_homelab/caps.py` lists every capability's fields.

For a real service:

- set `default_ports`;
- write `probe()`, so `bromigos setup homelab` can find the service;
- read from it with `self.get_json(path)` against `self.endpoint`. The source's TLS and
  credentials are applied for you.

List the hosts it talks to under `[permissions]` in `bromigos-ext.toml`, or `"any"` when
the user picks the endpoint. bromigOS's `docs/homelab.md` describes adapters in full.

## Try it

From the folder that holds this one:

```bash
bromigos ext validate ./__NAME__
bromigos ext install --copy ./__NAME__    # asks first, because it runs code
```

Then add a source to `~/.config/bromigos/homelab.toml`:

```toml
[[source]]
type = "__IDENT__"
```

Restart what reads it:

```bash
bromigos restart vector
bromigos restart widgets
```

After each edit, run `bromigos ext update __NAME__` and restart them again.

## Publish it

Put this folder in a Git repository, push it, and tag a release:

```bash
git tag v0.1.0 && git push --tags
```

People then install it with `bromigos ext install <your repository's URL>@v0.1.0`. To
list it in the catalog, see "Publish an extension" in bromigOS's `docs/extensions.md`.

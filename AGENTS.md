# AGENTS.md: bromigOS

Rules for AI coding assistants working in this repository. People follow the same rules,
in [CONTRIBUTING.md](CONTRIBUTING.md).

Start with [docs/README.md](docs/README.md), the docs by topic, and
[docs/PLAN.md](docs/PLAN.md), the plan and its decisions. CONTRIBUTING.md explains the
repository's layout and how to build and test it.

## Rules

- **Docs follow docs/WRITING.md.** Every Markdown file in this repository follows
  [docs/WRITING.md](docs/WRITING.md): plain words first, short sentences, terms defined,
  commands checked against the code, nothing described that isn't built.
- **Nothing operator-specific.** No hostnames, LAN addresses, tokens, Vault paths,
  likeness art, private voices or personal plugins. Those stay in a user's dotfiles:
  their thin configs, private overlay and plugin folders.
- **Every shipped asset needs a "yes" row** in [docs/ASSETS.md](docs/ASSETS.md),
  including images in the docs.
- **The name.** Never use "Arch" in the product's name. Say "based on Arch Linux".
- **One product.** bromigOS is a Bromigos product, separate from BRODEC.
- **Docs follow the code.** The command reference, the key table and the package tables
  are generated. After changing a command's help, a default key (and its description in
  `widgets/keybinds.py`) or a PKGBUILD, run `tools/docs/generate.py` with a built
  `bromigos` (`cargo build -p bromigos` in `core/`). CI's `docs` workflow fails when a
  generated section is stale or a link is broken.

# Packaging

bromigOS ships as pacman packages from its own signed repository, `[bromigos]`. Every
file it installs belongs to a package, so pacman handles updates, rollbacks and removal.
This folder holds the package recipes (PKGBUILDs) and the scripts that build, sign and
publish them.

## What's here

```text
packaging/
  keys/bromigos.asc        the repository's public signing key
  bromigos/                the meta-package: the whole desktop in one
  bromigos-keyring/        puts that key in pacman's keyring
  bromigos-core/           the bromigos command (core/), themes/, theme/, lib/, migrations/, bin/
  bromigos-desktop/        the desktop's default configs and their tools (desktop/)
  bromigos-settings/       the login screen, boot splash, boot menu, GTK, icon and cursor themes (settings/)
  bromigos-live/           the live layer (live/)
  bromigos-widgets/        the desktop panels (widgets/)
  bromigos-homelab/        the homelab integrations (homelab/)
  bromigos-lab-catalog/    the lab model catalog (homelab/share/lab/models.toml)
  bromigos-apps/           the app bundle's configs (apps/)
  bromigos-manual/         the manual (manual/), built as HTML to read offline
  herdr/, ttf-geist-mono/, 1password/, paru/
                           software Arch's repositories don't carry, built from upstream
                           sources pinned by checksum
  ci/publish.sh            build, sign, add to the database, upload, prune
  ci/prepare-container.sh  sets up the build container for publish.sh
  dev-repo.sh              your own build as a local repository, for the dev channel
  setup-repo.sh            adds [bromigos] to a machine by hand (install.sh does this now)
```

`bromigos-vector`, which holds VECTOR, the desktop's AI assistant, is built the same way
in the `bromigos-org/vector` repository. It's published into the same `[bromigos]`
repository.

For users, the manual's [What gets installed](../manual/src/packages.md) page lists the
packages. That table is generated from these PKGBUILDs.

## The packages

| Package | Installs | Built from |
|---|---|---|
| `bromigos` | Only its licences. It depends on the whole desktop and lists the optional pieces. | — |
| `bromigos-keyring` | The signing key in `/usr/share/pacman/keyrings/` | `keys/bromigos.asc` |
| `bromigos-core` | `/usr/bin/bromigos`, the themes, the theme templates, the shared Python libraries, the migrations and three pacman hooks | `core/`, `themes/`, `theme/`, `lib/`, `migrations/`, `bin/` |
| `bromigos-desktop` | The desktop's default configs in `/usr/share/bromigos/default/`, and the tools they call | `desktop/`, `peripherals/` |
| `bromigos-settings` | The SDDM login theme, the Plymouth splash, the GRUB boot theme, and the GTK, icon and cursor themes | `settings/`, the Wick's emblem kit, the den |
| `bromigos-live` | The live layer in `/usr/lib/bromigos/live/`, `/usr/bin/bromigos-live` and its default config | `live/` |
| `bromigos-widgets` | The panels in `/usr/lib/bromigos/widgets/`, `/usr/bin/bromigos-widgets` and the default layout | `widgets/` |
| `bromigos-homelab` | The homelab library, its decks, panels and VECTOR plugin, and `bromigos lab` | `homelab/` |
| `bromigos-lab-catalog` | The lab model catalog, `/usr/share/bromigos/homelab/lab/models.toml` | `homelab/share/lab/` |
| `bromigos-apps` | The app bundle's default configs and `bromigos apps setup` | `apps/` |
| `bromigos-manual` | The manual as HTML in `/usr/share/doc/bromigos/manual/`, which Settings opens | `manual/` |
| `herdr`, `ttf-geist-mono`, `1password`, `paru` | Upstream software, built here so no install needs an AUR helper | upstream sources, pinned by checksum |

Some packages need a closer look.

- **bromigos-keyring** installs `bromigos.gpg` and `bromigos-trusted`. Its install script
  runs `pacman-key --populate bromigos`, the way `archlinux-keyring` does. It skips this
  when pacman's keyring isn't set up yet, such as in a fresh chroot.
- **bromigos-core** installs the themes without their art pipeline files, which stay in
  the repository ([docs/art.md](../docs/art.md)). Its pacman hooks are
  `bromigos-update.hook`, which tells you to run `bromigos update` after bromigOS
  packages change, and the pair that holds Hyprland's reloads during a transaction
  ([core/README.md](../core/README.md)).
- **bromigos-desktop** installs `user/`, the thin files a user's `~/.config` starts from.
  It depends on the core, the live layer, the widgets and the apps the defaults run
  ([docs/desktop.md](../docs/desktop.md)).
- **paru** is the AUR helper. Its licence is GPL-3.0-or-later, installed in
  `/usr/share/licenses/paru/`.
  - `bromigos install` installs it unless told not to, and `bromigos update` updates AUR
    packages with it ([docs/aur.md](../docs/aur.md)).
  - It's the AUR's own recipe at the AUR's version, 2.1.0-2. So a paru someone built from
    the AUR stays in place.
  - It differs from the AUR's recipe in two ways. The alpm crates, which that recipe moves
    up with a bare `cargo update`, are pinned: alpm 4.0.4 and alpm-sys 4.0.5. And it
    depends on `base-devel`, which every AUR build needs.
  - It has no `provides`, `conflicts` or `replaces`, so paru-bin and paru-git are never
    swapped out.
- **bromigos-homelab** installs its library to `/usr/lib/bromigos/lib/bromigos_homelab/`
  and its decks, panels and VECTOR plugin to `/usr/lib/bromigos/homelab/`
  ([homelab/README.md](../homelab/README.md)).

Personal decks, shader layers and panels are plugins in the user's own folders. They
never go in these packages ([docs/plugins.md](../docs/plugins.md)).

## Building packages yourself

To build one package from this checkout:

```bash
cd packaging/bromigos-live
makepkg -f
git checkout -- PKGBUILD
```

`makepkg` rewrites the `pkgver=` line in the PKGBUILD. The last command undoes that, so
don't commit it.

To try your changes on your own machine, build every package into a local repository and
switch to the `dev` channel:

```bash
packaging/dev-repo.sh                # builds into ~/.local/share/bromigos/repo
bromigos channel dev                 # points pacman at it
bromigos update                      # installs your build
```

`dev-repo.sh DIR PACKAGE…` builds only the packages you name, into `DIR`. The local
repository is unsigned, because it's your own build. The published channels are signed
by CI.

## Adding a package

1. Make `packaging/<name>/PKGBUILD`. It builds from the checkout it lives in, so it has no
   `source=()` for our own code. Start it like this:

   ```bash
   _root="${startdir%/packaging/*}"      # the repository root
   _paths=(<folders this package is built from> packaging/<name>)
   ```

   Read from `$_root`. Write only under `$srcdir` and `$pkgdir`. For Rust, set
   `CARGO_TARGET_DIR="$srcdir/target"`.
2. Give it the `pkgver()` described under [Versions](#versions). Set
   `options=('!debug')` unless you want a `-debug` package published. Use
   `license=('MIT OR Apache-2.0')`, and install `LICENSE-MIT` and `LICENSE-APACHE` to
   `/usr/share/licenses/$pkgname/`.
3. Build it locally with `makepkg -f`, as above.
4. Push to `main`. CI builds it with the others and adds it to the same database.

Rust packages follow the Arch wiki's Rust package guidelines.

- Run `cargo fetch --locked` in `prepare()`.
- Use `--frozen` in `build()` and `check()`.
- Set `RUSTUP_TOOLCHAIN=stable`.
- Run `cargo test` in `check()`.
- Commit `core/Cargo.lock`.

## Versions

Each `pkgver()` computes the version from Git, counting only the commits that touch the
package's own paths (`_paths`):

```text
<base>.r<commits touching _paths>.g<newest such commit>     e.g. 0.1.2.r144.g1a2b3c4
```

- The count includes the commits made before this repository's history restarted at
  v0.1.2 (they're in `bromigos-org/bromigOS-archive`). Each PKGBUILD's `_archived` holds
  that package's number of them, so every version sorts above the ones published before
  the restart. Leave `_archived` as it is.

- `<base>` is the Cargo workspace version in `core/Cargo.toml`. Raising it there raises
  every package's version, even though the count goes on.
- The keyring's base is `0.0.0`. The third-party packages use their upstream versions.
- A commit that doesn't touch a package leaves its version alone, so CI doesn't publish
  it again.
- `pkgrel` stays `1`. Raise it only to republish the same source with a different
  PKGBUILD output, in the same commit as that change.

The count needs the whole history, so CI clones with `fetch-depth: 0`.

## Publishing

The workflow `.github/workflows/packages.yml` publishes the packages. It runs in these
cases:

- a push to `main` that touches the packaged folders, `install.sh`, the licences or the
  workflow itself;
- a version tag, `vX.Y.Z` or `vX.Y.Z-rcN`;
- by hand, with `gh workflow run packages`. The inputs are `rebuild`, `only` (some
  package folders), `channel` and `mirror_only`.

Pull requests never run it. It runs `ci/publish.sh` in an `archlinux:base-devel`
container. The script does this:

1. It imports the signing key into a throwaway keyring, and checks that it's the key in
   `keys/bromigos.asc`.
2. It copies `install.sh` and the public key to the repository's root, so a fix to the
   installer goes out even when no package changed.
3. For each `packaging/*/PKGBUILD`, it runs `pkgver()`. If that exact file is already
   published, it skips the package. Otherwise it installs the build dependencies, builds
   the package with `makepkg`, which runs `check()`, and signs it with a detached `.sig`.
4. It takes the repository's lock and downloads the current database. Then it runs
   `repo-add --verify --sign` to add the new packages to `bromigos.db` and
   `bromigos.files`.
5. It uploads the packages first, then the database. That way the database never names a
   file that isn't there yet.
6. When `bromigos-lab-catalog` was built, it also uploads the catalog with its own
   signature to `lab/models.toml`. `bromigos lab models refresh` fetches it from there
   ([docs/lab-models.md](../docs/lab-models.md)).
7. It keeps the newest three versions of each package and deletes older ones.
8. It copies the channel to the public mirror, still under the lease. See
   [The public mirror](#the-public-mirror).

A run with nothing new uploads nothing, unless the public mirror is behind.

Only one publisher may change the database at a time. Within this repository, the
workflow's `concurrency` group runs one publish per channel at a time. VECTOR's
repository publishes into the same database with this same script, so steps 4 to 7 run
under a lease: a `.publish-lock` object in the storage bucket. A lease older than 20
minutes belongs to a dead run, and the next run takes it over.

### Channels

A *channel* is which builds a machine follows. The repository has four.
[docs/update.md](../docs/update.md) describes them for users, and `bromigos channel`
switches a machine.

| Channel | Published by | Path in the bucket |
|---|---|---|
| `edge` | every push to `main` | `<repo>/<arch>/`, the original layout |
| `rc` | a `vX.Y.Z-rcN` tag | `<repo>/rc/<arch>/` |
| `stable` | a `vX.Y.Z` tag | `<repo>/stable/<arch>/` |
| `dev` | nobody; `dev-repo.sh` builds a local one | `file://…/repo/<repo>/<arch>` |

`publish.sh` reads the channel from `PKGS_CHANNEL`. The workflow sets it from the tag, or
from the `channel` input of a run by hand. Each channel has its own database, lease and
pruning.

A tag publishes the very same files the push to `main` built, with the same `pkgver()`.
So `stable` is exactly what was tagged. Nothing is rebuilt differently.

To release, tag both repositories that publish, because `bromigos` depends on
`bromigos-vector`. Push `vX.Y.Z` here and in `bromigos-org/vector`. `install.sh` and the
ISO follow `stable` by default.

### The public mirror

Every channel is published to two buckets. The homelab's bucket is the primary: CI reads
the current database from it and writes there first. A Google Cloud Storage bucket,
`gs://bromigos-pkgs` in the `bromigos-org` project, gets a copy. It's private until
bromigOS goes public, which is one command ([docs/public.md](../docs/public.md)).

`publish.sh` copies the channel to the mirror at the end of every publish, while it still
holds the lease. The order keeps the mirror valid for a pacman that reads it at any
moment:

1. the new packages and their signatures, and the signed lab catalog;
2. the databases, each with its signature straight after it;
3. last, deletions of whatever the primary pruned.

Until step 2, the old database names only files the mirror still has. The databases, the
catalog, `install.sh` and the key are uploaded with `Cache-Control: no-cache`. Then a public
cache never serves an old database beside a new signature.

If the copy fails, the run fails, but the primary is already published. The next run sees
that the mirror differs (`rclone check`) and copies the channel again. To bring a channel's
mirror up to date without building anything, run the workflow by hand:

```bash
gh workflow run packages -R bromigos-org/bromigOS -f channel=rc -f mirror_only=true
```

`manual/publish.sh` copies the web manual to the mirror the same way.

Without the `PKGS_GCS_*` secrets, `publish.sh` skips the mirror. A fork or a local run
then publishes to one bucket only.

### What CI needs

These repository secrets hold the publishing credentials. Their values live in the
deployment's secret store, never in this repository.

| Secret | What |
|---|---|
| `PKGS_S3_ENDPOINT` | The S3 endpoint of the storage bucket |
| `PKGS_S3_BUCKET` | The bucket. Packages go to `<bucket>/bromigos/x86_64/`. |
| `PKGS_S3_ACCESS_KEY_ID`, `PKGS_S3_SECRET_ACCESS_KEY` | A key that can write that bucket only |
| `PKGS_GPG_PRIVATE_KEY`, `PKGS_GPG_PASSPHRASE` | The signing key matching `keys/bromigos.asc` |
| `PKGS_GCS_BUCKET` | The public mirror's bucket, `bromigos-pkgs` |
| `PKGS_GCS_ACCESS_KEY_ID`, `PKGS_GCS_SECRET_ACCESS_KEY` | An HMAC key of the service account `bromigos-pkgs-publisher`, which may write that bucket only |

The secrets are only ever environment variables. `publish.sh` never prints them and never
passes them as arguments. It keeps the key in a temporary `GNUPGHOME` that it deletes on
exit.

The repository variable `CI_RUNNER_PACKAGES` names a self-hosted runner that can reach
the bucket. Without it, the job runs on GitHub's hosted runner.

A fork's pull request must never reach a self-hosted runner. So only pushes to `main`,
version tags and manual runs use the runners that `CI_RUNNER_PACKAGES` and
`CI_RUNNER_SMOKE` name. Every pull request's jobs run on GitHub's hosted runners, in the
same Arch container, and get no secrets. A workflow that a pull request starts must keep
that rule: its `runs-on` falls back to `ubuntu-latest` when `github.event_name` is
`pull_request`.

### Build times

One job builds every package whose files changed. Each `pkgver()` counts only its own
paths, and a file already in the bucket isn't rebuilt. Typical times on a self-hosted
runner:

| Step | Time |
|---|---|
| Container and Git | about 15 s |
| Checkout with full history | about 4 s |
| `bromigos-core`, a release build plus `cargo test` | 198 s cold, 95 s when one crate changed, 10 s unchanged |
| All the architecture-independent (`any`) packages | about 70 s in total |

On a self-hosted runner, the workflow mounts the runner's shared cache at `/ci-cache`.
`ci/prepare-container.sh` points cargo's registry (`CARGO_HOME`) and bromigos-core's
target folder (`BROMIGOS_CARGO_TARGET_DIR`, read by its PKGBUILD) there, so a rebuild
compiles only what changed. It clears the target folder when it grows past 6 GiB.
Elsewhere, builds start clean.

The `any` packages aren't built on arm64 runners, on purpose. They take about 70 s in
all. An Arch Linux ARM container would be pulled fresh on every job, and handing the
packages to a publish job adds transfers, so there's no gain. It's worth another look if
those builds grow. Their `.pyc` files would also need the same Python minor version on
both architectures.

## Using the repository

During early access the package repository is private. To get access, ask on the
[Bromigos Discord](https://discord.gg/8bjGcFvGZU). On a new machine, `install.sh` adds
the repository and its key ([docs/install.md](../docs/install.md)).

To add it by hand instead, run this once per machine, as root, from a checkout of this
repository:

```bash
sudo packaging/setup-repo.sh --dry-run <server>   # shows what it would change
sudo packaging/setup-repo.sh <server>
sudo pacman -S bromigos-core
```

`<server>` is the repository's base URL, and the script appends `/$repo/$arch`. You can
also set `BROMIGOS_REPO_URL`. There's no default. The script does this:

1. It checks that the server answers with a database.
2. It checks the key's fingerprint against the one written in the script, then trusts it
   with `pacman-key --add` and `--lsign-key`.
3. It writes this section to `/etc/pacman.conf`, after saving a backup to
   `/etc/pacman.conf.bromigos.bak`:

   ```ini
   [bromigos]
   SigLevel = Required DatabaseOptional
   Server = <server>/$repo/$arch
   ```

4. It runs `pacman -Sy` and installs `bromigos-keyring`.

It's safe to run again. Each step checks first and changes only what differs.

## Rotating the signing key

1. Generate the new key.
2. Publish a `bromigos-keyring` that carries both keys, with both fingerprints in
   `bromigos-trusted`.
3. Wait for it to reach every machine.
4. Switch CI's secrets to the new key.
5. Drop the old key from the keyring, and list it in a `bromigos-revoked` file.

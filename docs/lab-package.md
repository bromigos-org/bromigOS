# The standalone lab package

`bromigos-lab` is the console, adapters, model catalog and provisioning on plain Arch
Linux. It needs Python and Textual, a terminal interface library. Desktop integrations
are optional. Users can follow [Install on plain Arch](../manual/src/lab.md#install-on-plain-arch).

## Package ownership

Both the signed-repository recipe and the AUR recipe call `packaging/install-lab.sh`.
The split keeps the existing paths so desktop consumers and user configs keep working.

| Package | Owns |
|---|---|
| `bromigos-lab` | `/usr/bin/bromigos-lab`, the library and commands under `/usr/lib/bromigos/`, lab services, profiles and documented defaults |
| `bromigos-homelab` | Desktop panels, decks, VECTOR plugins, launcher entries and the rack hologram |
| `bromigos-lab-catalog` | The independently updated desktop model catalog |

`bromigos-homelab` depends on `bromigos-core`, `bromigos-lab` and `bromigos-lab-catalog`.
The standalone package has no required bromigOS dependency. Its optional tools cover
SSH, Ansible, Kubernetes, Helm, encrypted credentials and VM providers. The optional
`bromigos-homelab` package adds desktop integrations. Art jobs, desktop target commands
and Den TV media tools need `bromigos-core`.

The standalone package includes `/usr/share/bromigos-lab/models.toml`. Catalog reads
prefer a verified refreshed copy, then the independently updated desktop catalog, then
this fallback. The user override still comes first. The package also bundles the
public verification key for signed catalog refreshes. `gnupg` is optional at runtime
for these refreshes; no desktop keyring package is required. Profiles retain their existing path.
The public config defaults have no sources. No install creates user config or enables
services. Both commands use `~/.config/bromigos/homelab.toml` and the same state paths.

## Source releases and AUR publication

`packaging/aur/bromigos-lab/PKGBUILD.in` is a recipe template. The release job renders a
real `PKGBUILD` with a fixed version, source tag and SHA-256 checksum. It has no VCS
version function and never skips checksum verification. This follows Arch's
[AUR submission guidelines](https://wiki.archlinux.org/title/AUR_submission_guidelines).

`release-lab.yml` runs for a component tag such as `bromigos-lab-v0.1.0`. It can also
be called by the main release workflow after a stable `vX.Y.Z` release, or dispatched
with an existing stable tag. It verifies that checkout HEAD is the tag's commit.
Then it downloads that tag's source archive and pins the recipe to its checksum.
Older tags without the split installer cannot pass this gate.

Before publication, a disposable `archlinux:base-devel` container builds and installs
the exact recipe. It has no bromigOS packages beforehand. Afterward, the only package
whose name starts with `bromigos` is `bromigos-lab`. The test runs:

- `bromigos-lab --help` and the existing internal CLI path.
- Doctor in text and JSON, against a loopback fake Ollama service.
- The bundled model catalog and provisioning imports.
- Textual's headless pilot through Status, Models, Jobs, Doctor and Provision.
- A file ownership check against the desktop integration package.

The source package's unit tests run through `makepkg` too. The container is limited to
4 GB RAM and two CPUs. It opens no windows and connects to no real lab or messaging bot.
Root commands run inside the container only.

Only after the container succeeds does the existing AUR deployment action receive
`AUR_SSH_PRIVATE_KEY`. It publishes as the configured AUR account, with the maintainer
line `bromigOS <packages@bromigos.org>`. The job saves the pinned recipe as an artifact.
Component tags also get a GitHub release after publication. Tags are never moved.

## Running the gate locally

Render a recipe from an existing release tag and run the container:

```bash
python packaging/ci/prepare-aur-lab.py bromigos-lab-v0.1.0
docker run --rm --memory=4g --cpus=2 --pids-limit=512 \
  -v "$PWD:/work:ro" archlinux:base-devel \
  bash /work/packaging/ci/test-aur-lab.sh /work
```

For a source change before tagging, `prepare-aur-lab.py --archive <archive>` accepts
a local test archive. Put it in a source-cache folder under the filename named by the
recipe. Pass that folder as the test script's second argument. The publication workflow
always downloads the real tagged archive and reruns the test. A local pass cannot bypass
that test or publish an unpinned source.

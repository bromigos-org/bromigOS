# Releasing bromigOS

A release is a version number, a tag, notes for the people who use bromigOS, and the
packages of that tag on a channel. bromigOS and VECTOR are released together: the same
version, tagged in both repositories, published to the same channel, with VECTOR's notes as
a section of bromigOS's.

Three workflows do it, all started from GitHub Actions; nothing is tagged by hand.

| Workflow | Started by | What it does |
|---|---|---|
| **release-prepare** | you (Run workflow) | picks the version, drafts the notes, opens the release PR |
| **release** | merging the release PR | checks the guard rails, tags both repositories, publishes, creates the GitHub Releases |
| **release-promote** | you (Run workflow) | makes a release candidate the stable release, without rebuilding |

The channels themselves (stable, rc, edge, dev) are in [update.md](update.md): every push to
main is on edge; a `vX.Y.Z-rcN` tag publishes the rc channel; a `vX.Y.Z` tag the stable one.

## Cutting a release candidate

1. Make sure main is green (the release refuses otherwise).
2. Actions → **release-prepare** → Run workflow:
   - **version**: `patch`, `minor` or `major` (counted from the last stable release), or an
     exact `0.2.0`;
   - **kind**: `rc`;
   - **dry run**: off (leave it on to try the whole thing without a real PR: see "Dry runs").
3. A few minutes later there are two PRs: `release: v0.1.2-rc1` in bromigOS, and its VECTOR
   side in bromigos-org/vector. Read the bromigOS one: its description shows the notes as
   users will see them. Edit `manual/src/whats-new.md` on the PR's branch to change them.
   Leave the VECTOR PR alone: it lands by itself.
4. Merge the bromigOS PR with **Create a merge commit** (not squash or rebase: the tag goes
   on the PR's own release commit, which has to stay in main's history).
5. The **release** workflow then tags `v0.1.2-rc1` in both repositories, waits for the rc
   channel to be published, and creates the two GitHub Releases (marked pre-release).

Anyone on the rc channel (`bromigos channel rc`) gets it with `bromigos update`.

A second candidate for the same version is the same steps: release-prepare with `patch` and
`rc` gives `v0.1.2-rc2`, and its notes replace rc1's (they always cover everything since the
last stable release).

## Promoting a release candidate to stable

Actions → **release-promote** → Run workflow, with the candidate (`v0.1.2-rc2`; empty means
the newest) and dry run off. It tags `v0.1.2` on the very commits `v0.1.2-rc2` tagged, in both
repositories. The stable channel's publish then copies the rc channel's packages, signatures
and all, instead of building them again (packaging/ci/publish.sh, `PKGS_REUSE`): stable gets
exactly what rc users tested. The GitHub Releases reuse the candidate's notes, with a line
saying it was promoted unchanged.

Nothing is committed, so the notes installed on machines are the candidate's, word for word:
their date line still says "Release candidate 0.1.2-rc2", which the page explains.

Only the newest candidate of a version can be promoted.

## Releasing straight to stable

release-prepare with **kind** `stable` makes a `v0.1.2` PR; merging it publishes the stable
channel directly. Use it for small fixes that don't need a candidate. The stable channel
still takes the packages main already built (edge) where they're the same build, and builds
only what isn't.

## What the notes contain

**For users** (`manual/src/whats-new.md`, one section per release, newest first):

- a one- or two-sentence summary;
- **Before you update**: anything to know or do first (a password prompt from a migration,
  a log out, a reboot). Usually "Nothing to do";
- **New**, **Improved**, **Fixed**, in plain words;
- **VECTOR**: VECTOR's own New, Improved and Fixed;
- **Known issues**: the open issues labelled `known-issue` in either repository, and
  limitations a commit states. "None known." when there are none.

They're drafted by the homelab's local model (the `qwen3.8-flash-next` alias, through the
homelab's LiteLLM) from git-cliff's grouping of every commit since the last stable release,
the commit bodies, the new migrations and the open known issues. It's a draft: the PR is the
review. They show up:

- in the manual, as the What's new page;
- on every machine, offline: bromigos-core installs the page, `bromigos whats-new` prints
  the newest release (`--all` for every one), and the first `bromigos update` after a new
  release ends with `== what's new: bromigOS 0.1.2 (bromigos whats-new)`;
- in the GitHub Release, with how to update, the links, and the checksums.

**For developers** (`CHANGELOG.md`): every commit, grouped by area (Desktop, Core, Live
layer…; VECTOR's by Added, Changed, Fixed), with links. It's git-cliff's
(`tools/release/cliff.toml`), not edited by hand. VECTOR's repository keeps its own
CHANGELOG.md the same way.

**The version**: `core/Cargo.toml`'s workspace version (and `core/Cargo.lock`) becomes the
release's, so every bromigOS package's version starts with it (`0.1.2.r140.g…`); VECTOR's
`VERSION` file likewise for bromigos-vector. A release candidate already carries the final
version: `0.1.2` for `v0.1.2-rc1`, so the stable release is the same build.

### What the notes may not say

The generated text goes through the same privacy guard as the rest of our repositories
(`tools/release/privacy_guard.py`, VECTOR's copy of the dotfiles' guard: private addresses,
internal host names, token shapes, and the lab's own names from the `PRIVACY_PATTERNS`
secret), and through rules of its own (`tools/release/guard.py`): no internal project
names, no other distribution named, no names or e-mail addresses of the commits' authors,
no cluster service names. The model's input has those removed already; a
draft that still says one is sent back to the model, and after four tries the run stops.
The changelog keeps each commit, but a subject that breaks a rule reads "(withheld by the
privacy check)" with its link. The release workflow checks the GitHub Release's text again
before it creates it.

## Guard rails

- **No release from a red main.** release-prepare checks that every workflow's newest
  finished run on main is green, in both repositories; release waits for the merge
  commit's own runs and checks again before tagging.
- **Tags are on main.** The release commit has to be in main's history before it's
  tagged, and packages.yml (in both repositories) refuses to publish a tag that isn't on
  main, however it was pushed.
- **Nothing is tagged twice.** A version that exists in either repository can't be prepared
  or tagged again.
- **What was reviewed is what's tagged.** The tag goes on the PR's release commit, not on
  whatever main has by the time it's merged; VECTOR's release commit has to be the one the
  PR names, on the commit its notes were drafted from.
- **The notes pass the privacy check** (above).
- **Stable isn't rebuilt from an rc.** A promotion copies the rc channel's signed packages;
  their signatures are checked on the way.

## How the two repositories move together

bromigOS's workflows drive both, with one fine-grained token (`RELEASE_TOKEN`); VECTOR's
repository needs no release workflow of its own.

1. release-prepare reads both histories, drafts both sets of notes, and pushes VECTOR's
   release commit (`VERSION`, its `CHANGELOG.md`) to a `release/vX.Y.Z` branch in vector,
   with a PR there for the record. bromigOS's release commit names that commit in
   `tools/release/current.json`.
2. When the bromigOS PR is merged, release lands VECTOR's commit on vector's main (a
   fast-forward, or a merge commit when vector's main moved on meanwhile), tags it, then
   tags bromigOS. Each tag starts that repository's own packages.yml, which publishes to the
   channel the tag names; the two share one repository database under its lease.
3. It waits for both publishes, then creates both GitHub Releases. VECTOR's release links to
   bromigOS's.

## Fixing a bad release

**Never move or reuse a tag that published.** Machines already have its packages, and a
version means one build. Fix forward instead:

- a bad **release candidate**: fix it on main and prepare the next candidate (`-rc2`), or
  simply don't promote it;
- a bad **stable release**: fix it on main and release a patch (`v0.1.3`), straight to
  stable when it's urgent.

**Withdrawing it** while the fix is on its way:

1. Say so on the GitHub Release: `gh release edit v0.1.2 --prerelease --title "bromigOS 0.1.2
   (withdrawn)"`, and add a line at the top of its notes saying what's wrong and what to do.
   Do the same on vector's release.
2. If people must not get it at all, put the channel back to the previous release: run
   packages.yml on the previous tag with a rebuild, in both repositories:

   ```text
   gh workflow run packages.yml -R bromigos-org/bromigOS --ref v0.1.1 -f channel=stable -f rebuild=true
   gh workflow run packages.yml -R bromigos-org/vector   --ref v0.1.1 -f channel=stable -f rebuild=true
   ```

   The database then names the older packages again. Machines that haven't updated stay as
   they are; machines that have keep the bad version until they downgrade (below).
3. Add a `known-issue` issue, so the next release's notes mention it if it isn't fixed yet.

**What to tell users**, in the withdrawn release's notes:

- `bromigos update --rollback` undoes the update: every file the update changed comes back
  from the snapshot taken before it ([update.md](update.md), "Rolling back");
- if the machine doesn't boot, pick the "before bromigos update" snapshot in the boot menu,
  then run `bromigos update --rollback` from there;
- once the channel is back on the previous release, `bromigos update --downgrade` brings a
  machine to it; or they wait for the fix, which arrives with a plain `bromigos update`.

## Dry runs

Every workflow has a **dry run** switch, on by default.

- **release-prepare**, dry: the same notes, changelog and version, but on
  `release-dryrun/vX.Y.Z` branches, as draft PRs. The release workflow ignores those
  branches, so merging one would tag nothing; close them when done. Without the model's key
  it drafts from the commit subjects instead, and says so.
- **release**, dry (Run workflow, with the tag and the dry-run branch as **ref**): every
  guard, reported rather than enforced; the GitHub Release's text and the current channel's
  checksums, signed, in the run's summary and artifact; the tags, pushes and releases it
  would make, printed as `would: …`.
- **release-promote**, dry: the same for a promotion.

## The ISO

The installer image is built and tested by hand ([iso.md](iso.md)): it needs a privileged
container, ~15 GB of disk and KVM, more than the shared runners give. When one is built from
a release's tag, attach it with its checksum:

```text
gh release upload v0.1.2 ~/.cache/bromigos-iso/bromigos-*-x86_64.iso ~/.cache/bromigos-iso/bromigos-*-x86_64.iso.sha256
```

## The public repository

Every channel a release publishes is also copied to a Google Cloud Storage bucket, which is
private during early access. Making it public is one command, run once:

```bash
tools/release/go-public.sh          # checks, and prints what it would do
tools/release/go-public.sh --yes    # opens the bucket and lands the prepared changes
```

[public.md](public.md) explains what it does, what it costs and how to undo it.

## Known limitations

- **One web manual for every channel.** CI publishes the manual from `main`
  (`.github/workflows/manual.yml`), so the copy at `<repo>/bromigos/manual/` describes
  `edge`, even to a machine on `stable`. A release doesn't publish one of its own, since
  `manual/publish.sh` has one destination. Each machine's installed copy (the
  `bromigos-manual` package) is built with its own packages and matches them, and Settings
  opens that copy first ([update.md](update.md#the-manual)).

## What CI needs

Besides what packages.yml already has (packaging/README.md, "What CI needs"):

| Setting | Kind | What |
|---|---|---|
| `RELEASE_TOKEN` | secret | a fine-grained token for bromigos-org/bromigOS and bromigos-org/vector: Contents, Pull requests and Actions read and write. It pushes the release branches and tags (a tag pushed with a workflow's own token starts no workflow, so packages.yml wouldn't run) and opens the PRs (the repositories don't let Actions open them) |
| `LITELLM_API_KEY` | secret | a LiteLLM key that may use the `qwen3.8-flash-next` model |
| `LITELLM_BASE_URL` | variable | the LiteLLM address the runners reach |
| `PRIVACY_PATTERNS` | secret | the lab's own names, one regular expression per line: the dotfiles' list, plus anything else the notes must never say |

The release runs on the homelab runners (`CI_RUNNER_SMOKE` for preparing, `CI_RUNNER_PACKAGES`
for tagging and checksums, which reads the packages' bucket).

## Files

| File | What |
|---|---|
| `.github/workflows/release-prepare.yml`, `release.yml`, `release-promote.yml` | the three workflows |
| `.github/workflows/release-tools.yml` | the tool's tests, on every change to it |
| `tools/release/release.py` | the version, the notes, the files, the GitHub Release's text, the CI check |
| `tools/release/prompt.md` | what the model is told |
| `tools/release/cliff.toml` | git-cliff's grouping of our commit subjects |
| `tools/release/guard.py`, `privacy_guard.py` | the privacy check |
| `tools/release/checksums.sh` | SHA256SUMS from the channel's signed database, signed |
| `tools/release/go-public.sh`, `test_go_public.py` | making the package repository public ([public.md](public.md)), and its tests |
| `tools/release/current.json` | written by each release PR: the release its commit prepares |
| `CHANGELOG.md`, `manual/src/whats-new.md` | the technical log, and the notes for users |

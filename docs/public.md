# Making the package repository public

bromigOS's packages are public, at `https://pkgs.bromigos.org`. CI copies every channel to that Cloudflare R2
bucket, which serves them to anyone with no charge for downloads. During early access the
bucket was private, and `tools/release/go-public.sh` opened it.

This page explains what's ready, what the command does, what it costs and how to undo it.
[packaging/README.md](../packaging/README.md#the-public-mirror) explains how CI keeps the
copy current.

## What's ready

| Piece | State now |
|---|---|
| The bucket, `bromigos-pkgs` | In the Bromigos Cloudflare account's R2. Public access is off: no r2.dev address and no custom domain. |
| Its writer | An R2 API token that may read and write this bucket only. CI uses its S3 key, because `publish.sh` speaks the S3 protocol. |
| The copy | Every publish, in both repositories, copies its channel to the bucket under the same lease. The manual is copied too. |
| `install.sh` | It reads its default repository from `PUBLIC_REPO`, which is empty. Without `--repo` it stops, as before. |
| The go-live changes | Two prepared branches: `go-public` in bromigOS, and `os-get-public` in bromigos.org. They carry the bucket's r2.dev address. Neither is merged. |

R2 keeps no old versions of an object. The bucket holds the same paths as the homelab's:

```text
bromigos/install.sh, bromigos/bromigos.asc    the bootstrap and the public key
bromigos/x86_64/                              the edge channel
bromigos/rc/x86_64/, bromigos/stable/x86_64/  the rc and stable channels
bromigos/manual/                              the web manual
```

## Before you go public

- **Check the proprietary packages.** The lab's repository builds `1password` from
  1Password's own download, under a proprietary licence. The mirror leaves it out:
  `publish.sh` copies no file of it, and the mirror's databases are the lab's with it
  removed, signed again with the same key. Public users get it from the AUR
  (`bromigos install --with 1password`). The command's checks name any package whose
  licence is proprietary that is still in the mirror's edge database.
- **Check the mirror is current.** The command checks that every channel's database is on
  the mirror and verifies against the signing key. To copy a channel again without building
  anything, run
  `gh workflow run packages -R bromigos-org/bromigOS -f channel=<channel> -f mirror_only=true`.
- **Choose the address.** See [The address](#the-address).
- **Rebase the prepared branches** if main has moved a lot. The command rebases them
  itself, and stops before changing anything if either one conflicts.

## Going public

The command needs a Cloudflare API token that may edit R2, the account's ID, and the
mirror's S3 key. It reads them from the environment, or from the bucket's record in Vault
when `GO_PUBLIC_VAULT_PATH` names it. The script's header lists the variables. It never
prints them or puts them on a command line.

From a bromigOS checkout, signed in to GitHub:

```bash
tools/release/go-public.sh                 # checks everything, and prints what it would do
tools/release/go-public.sh --yes           # does it, at the r2.dev address
tools/release/go-public.sh --domain pkgs.bromigos.org --yes    # or at a custom domain
```

Without `--yes` it changes nothing. With `--yes` it does this, in order:

1. **It checks.** It reads the bucket with the mirror's S3 key. The key must be the one
   `install.sh` pins, and every channel's database must verify against it. Both prepared
   branches must exist and merge cleanly into main.
2. **It turns on the public address.** Either the bucket's r2.dev address, or with
   `--domain` a custom domain in a Cloudflare zone of the same account.
3. **It downloads as a stranger would**, with no credentials. It fetches `install.sh`, the
   key, and every channel's database and signature, and verifies them. If anything fails,
   it stops here, and the repositories are untouched.
4. **It lands bromigOS's `go-public` branch on main.** `install.sh` then defaults to the
   public repository, and the README, the install docs and the manual drop the early
   access notes. With `--domain`, the r2.dev address on the branch becomes the custom one
   first. The next publish copies the new `install.sh` to both buckets.
5. **It lands bromigos.org's `os-get-public` branch on main** the same way. That deploys
   the site, and the /os/get page shows the install steps instead of the Discord note.

With `GO_PUBLIC_VAULT_PATH` set, it also marks the bucket's record in Vault public.
This step leaves the GitHub repositories as they are. `--repos` makes them public:
see [The GitHub repositories](#the-github-repositories).

### The same bucket change by hand

In the Cloudflare dashboard: R2, `bromigos-pkgs`, Settings, Public access. Allow the
r2.dev subdomain, or connect a custom domain. Through the API, the r2.dev address is:

```bash
curl -X PUT -H "Authorization: Bearer <token>" -H 'Content-Type: application/json' \
  --data '{"enabled":true}' \
  https://api.cloudflare.com/client/v4/accounts/<account>/r2/buckets/bromigos-pkgs/domains/managed
```

### Undo

```bash
tools/release/go-public.sh --private --yes                       # the r2.dev address
tools/release/go-public.sh --private --domain pkgs.bromigos.org --yes
```

This turns the public address off again. It doesn't revert the two merged branches. Revert
those with `git revert` if you need to.

## The GitHub repositories

At go-live, the GitHub repositories `bromigOS`, `vector` and `extensions` become public
too. Their histories start at v0.1.2 for that reason. The `-archive` repositories, which
hold the earlier history, stay private. One command does it, after the steps above:

```bash
tools/release/go-public.sh --repos            # prints everything it would change
tools/release/go-public.sh --repos --yes      # changes it
```

Without `--yes` it changes nothing. With `--yes` it does this, in order:

1. **It moves CI to GitHub's runners**, in bromigOS and vector. Public repositories never
   use the homelab's runners: a fork's pull request could run code on them. GitHub's
   hosted runners are free for public repositories.
   - It deletes every `CI_RUNNER_*` variable. Every job then runs on GitHub's runner.
     `packages.yml` publishes to the R2 bucket alone, and the homelab copies from it
     ([packaging/README.md](../packaging/README.md#when-the-public-bucket-is-the-primary)).
   - It sets the secret `LITELLM_BASE_URL` to the model's public address, so
     release-prepare still drafts the notes. It checks first that the address answers.
     It deletes the variable of that name, whose value would show in public logs.
   - It sets the variable `ISO_REPO_URL` to the public package repository, once
     `install.sh` names one. Otherwise it deletes it.
   - It lists runs still queued for a homelab runner, with the commands to start them
     again.
2. **It makes each repository public.**
3. **It turns on what a public repository needs**, in each one:
   - private vulnerability reporting, so a security problem can be reported privately;
   - secret scanning with push protection, which refuses a push that contains a secret;
   - approval for workflow runs from every outside contributor's fork
     (`all_external_contributors`).

It reads the model's public address from `GO_PUBLIC_LITELLM_PUBLIC_URL`, or from a record
in Vault that `GO_PUBLIC_CI_VAULT_PATH` names. The script's header lists the names.

`--ci` does step 1 alone. `tools/release/go-public.sh --ci --private --yes` puts the
homelab's runners and the in-cluster address back. The first publish on a homelab runner
then takes the primary back from R2. The command never makes a repository private again.
Do that by hand with `gh repo edit <repo> --visibility private
--accept-visibility-change-consequences`, then run `--ci --private`.

Every workflow takes a `hosted` input, which runs it on GitHub's runner while the
variables still name the homelab's. Use it to check a change before the switch. While the
repositories are private, those runs count against the account's free minutes.

## What it costs

R2 doesn't charge for downloads. That's why the packages are there.

| What | Free each month | Then |
|---|---|---|
| Storage | 10 GB | $0.015 per GB a month |
| Reads (class B operations) | 10 million | $0.36 per million |
| Writes (class A operations) | 1 million | $4.50 per million |

The repository is about 1 GB per channel at most: three channels, three versions of each
package. A new install reads about 30 files. Early on, all of it fits in the free tier.

## The address

| Option | Address | Cost | Notes |
|---|---|---|---|
| r2.dev (the default) | `https://pub-<id>.r2.dev` | Free | Works without DNS. Cloudflare rate-limits it, doesn't cache it, and calls it unsuitable for production traffic. |
| A custom domain | `https://pkgs.bromigos.org` | Free | Cached by Cloudflare's network, with no rate limit. Needs bromigos.org's DNS on Cloudflare. `--domain` sets it up. |

The address is written into every machine's `/etc/pacman.conf`. Moving later needs a
migration that rewrites the `Server` line, so choose before many people install. The
custom domain is the better long-term address. While bromigos.org's DNS is elsewhere,
r2.dev is the only one available.

The v0.1.2 ISO names the r2.dev address. Every machine installed from it has that
address in its `/etc/pacman.conf`. So with `--domain`, the command keeps the r2.dev
address on as well, and those machines keep getting updates. `--private --domain` turns
both off. ISOs built after go-live name the custom domain
(`iso/build.sh --medium-repo https://pkgs.bromigos.org`), so new installs use it.

## The signing key

Every package and every database is signed with the bromigOS key:

```text
393E 7D54 F7DE 58FE 75B9  7214 947C 9D61 93D3 DD8B
```

It's published in four places:

- `install.sh`, which pins the fingerprint and refuses any other key;
- the `bromigos-keyring` package, which puts it in pacman's keyring;
- `packaging/keys/bromigos.asc` in this repository, and `bromigos/bromigos.asc` in the bucket;
- the /os/get page on bromigos.org, which shows the fingerprint.

The private key and its passphrase are in the deployment's secret store and in CI's
secrets, never in a repository. To replace the key, follow
[Rotating the signing key](../packaging/README.md#rotating-the-signing-key).

## Files

| File | What |
|---|---|
| `tools/release/go-public.sh` | The command; `--repos` makes the GitHub repositories public, `--ci` moves CI to GitHub's runners |
| `tools/release/test_go_public.py` | Its tests, with a stubbed Cloudflare API and bucket, and throwaway repositories |
| `packaging/ci/publish.sh` | Publishes each channel, then copies it to the mirror |
| `manual/publish.sh` | Publishes the web manual to both buckets |
| `install.sh` | `PUBLIC_REPO`, the default repository |

# Making the package repository public

bromigOS's packages are private during early access. CI already copies every channel to a
Google Cloud Storage bucket that is ready to serve them to anyone. Making it public is one
command, `tools/release/go-public.sh`. Nothing is public until someone runs it with
`--yes`.

This page explains what's ready, what the command does, what it costs and how to undo it.
[packaging/README.md](../packaging/README.md#the-public-mirror) explains how CI keeps the
copy current.

## What's ready

| Piece | State now |
|---|---|
| The bucket, `gs://bromigos-pkgs` | In the `bromigos-org` project, US multi-region. Public access prevention is on, so nobody outside the project can read it. |
| Its writer | The service account `bromigos-pkgs-publisher@bromigos-org.iam.gserviceaccount.com`. It may write this bucket only. CI uses its HMAC key, because `publish.sh` speaks the S3 protocol. |
| The copy | Every publish, in both repositories, copies its channel to the bucket under the same lease. The manual is copied too. |
| `install.sh` | It reads its default repository from `PUBLIC_REPO`, which is empty. Without `--repo` it stops, as before. |
| The go-live changes | Two prepared branches: `go-public` in bromigOS, and `os-get-public` in bromigos.org. Neither is merged. |

The bucket keeps no old versions. Versioning and soft delete are off, and a lifecycle rule
deletes any noncurrent object. It holds the same paths as the homelab's bucket:

```text
bromigos/install.sh, bromigos/bromigos.asc    the bootstrap and the public key
bromigos/x86_64/                              the edge channel
bromigos/rc/x86_64/, bromigos/stable/x86_64/  the rc and stable channels
bromigos/manual/                              the web manual
```

## Before you go public

- **Check the proprietary packages.** The repository builds `1password` from 1Password's
  own download. Its licence is proprietary. A public mirror redistributes it to anyone, so
  check that 1Password's terms allow that. If they don't, drop it from the repository
  first, and point users at the AUR. The command's checks name every package whose licence
  is proprietary.
- **Check the mirror is current.** The command checks that every channel's database is on
  the mirror and verifies against the signing key. To copy a channel again without building
  anything, run
  `gh workflow run packages -R bromigos-org/bromigOS -f channel=<channel> -f mirror_only=true`.
- **Rebase the prepared branches** if main has moved a lot. The command rebases them
  itself, and stops before changing anything if either one conflicts.

## Going public

From a bromigOS checkout, signed in to gcloud as an owner of `bromigos-org` and to GitHub:

```bash
tools/release/go-public.sh          # checks everything, and prints what it would do
tools/release/go-public.sh --yes    # does it
```

Without `--yes` it changes nothing. With `--yes` it does this, in order:

1. **It checks.** The bucket is reachable, the mirror's key is the one `install.sh` pins,
   and every channel's database verifies against it. Both prepared branches exist and
   merge cleanly into main.
2. **It opens the bucket.** It turns public access prevention off, and lets `allUsers`
   read objects (`roles/storage.legacyObjectReader`). Nobody can list the bucket.
3. **It downloads as a stranger would**, with no credentials. It fetches `install.sh`, the
   key, and every channel's database and signature, and verifies them. If anything fails,
   it stops here, and the repositories are untouched.
4. **It lands bromigOS's `go-public` branch on main.** `install.sh` then defaults to the
   public repository, and the README, the install docs and the manual drop the early
   access notes. The next publish copies the new `install.sh` to both buckets.
5. **It lands bromigos.org's `os-get-public` branch on main.** That deploys the site, and
   the /os/get page shows the install steps instead of the Discord note.

With `GO_PUBLIC_VAULT_PATH` set to the bucket's record in Vault, it also marks the record
public.

The command never changes gcloud's default project. It passes `--project bromigos-org`
and `--billing-project=bromigos-org` on every call. The GitHub repositories stay private.

Once it's done, anyone installs bromigOS like this:

```bash
curl -fsSLO https://storage.googleapis.com/bromigos-pkgs/bromigos/install.sh
less install.sh
bash install.sh
```

### The same steps by hand

These are the bucket commands the script runs:

```bash
gcloud storage buckets update gs://bromigos-pkgs --no-public-access-prevention \
  --project bromigos-org --billing-project=bromigos-org
gcloud storage buckets add-iam-policy-binding gs://bromigos-pkgs \
  --member=allUsers --role=roles/storage.legacyObjectReader \
  --project bromigos-org --billing-project=bromigos-org
curl -fsSI https://storage.googleapis.com/bromigos-pkgs/bromigos/install.sh
```

The last command should answer `200` within a minute.

### Undo

```bash
tools/release/go-public.sh --private --yes
```

This removes the `allUsers` grant and turns public access prevention back on. It doesn't
revert the two merged branches. Revert those with `git revert` if you need to.

## What it costs

Storage is small: three channels, three versions of each package, about 3 GB at most. At
about $0.026 per GB a month, that's under $0.10 a month.

Downloads cost more. Data leaving Google Cloud for the internet costs about $0.12 per GB.

- A new install downloads about 0.1 GB of bromigOS packages, so about $0.01. With
  `1password` it's about 0.3 GB.
- An update downloads only the packages that changed. `bromigos-core`, the largest, is
  about 70 MB.

A thousand installs a month cost about $12 to $36. Set a budget alert on the
`bromigos-org` billing account before you go public.

## A nicer address

The public address is `https://storage.googleapis.com/bromigos-pkgs`. It's free, it uses
Google's own TLS certificate, and it needs no DNS. It's the default.

The address is written into every machine's `/etc/pacman.conf`. Moving later needs a
migration that rewrites the `Server` line, so choose before many people install.
bromigos.org's DNS is with its registrar, not Cloudflare, so Cloudflare's proxy isn't an
option without moving the DNS first.

| Option | Address | Cost | Notes |
|---|---|---|---|
| The storage path (default) | `storage.googleapis.com/bromigos-pkgs` | Free | Works now. Not our domain. |
| A load balancer | `pkgs.bromigos.org` | About $18 a month, plus egress | A global external Application Load Balancer with a backend bucket and a Google-managed certificate. One A record at the registrar. Cloud CDN can be turned on in front of it. |
| Firebase Hosting | `bromigos.org/...` | Free | Hosting rewrites can't serve a Cloud Storage bucket. A redirect (`"redirects"` in `firebase.json`) can point `/pkgs/**` at the storage path. pacman and curl follow redirects, but every file costs an extra round trip. Not tested. |
| A CNAME to `c.storage.googleapis.com` | `pkgs.bromigos.org` | Free | HTTP only, with no TLS. Not suitable. |

To use another address, set `GO_PUBLIC_URL` when you run the command, and set the same
value as `PUBLIC_REPO` on the `go-public` branch. The command checks that the two match.

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
| `tools/release/go-public.sh` | The command |
| `tools/release/test_go_public.py` | Its tests, with stubbed gcloud and curl and throwaway repositories |
| `packaging/ci/publish.sh` | Publishes each channel, then copies it to the mirror |
| `manual/publish.sh` | Publishes the web manual to both buckets |
| `install.sh` | `PUBLIC_REPO`, the default repository |

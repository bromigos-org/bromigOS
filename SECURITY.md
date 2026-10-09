# Security

This page says how to report a security problem in bromigOS, and what happens after you
do. Please report it privately, so it can be fixed before anyone else hears about it.

## Report a problem

Don't open a public issue for a security problem. Use one of these instead:

- **GitHub's private report.** Open the repository's **Security** tab and choose **Report
  a vulnerability**. Only the maintainers see it.
- **Email.** Write to contact@bromigos.org with "Security" at the start of the subject.

Tell us:

- what is affected: the package, or the file in this repository;
- the version and channel, from `bromigos about`;
- how to reproduce the problem, step by step;
- what an attacker could do with it.

Leave out anything private, such as your hostnames, addresses or tokens. We don't need
them.

## What happens next

We reply to say we have your report. We tell you whether we can reproduce the problem,
and we keep you posted until it's fixed. When the fix ships, we credit you in the release
notes, unless you'd rather we didn't.

Please give us a fair chance to ship a fix before you tell anyone else.

## What this covers

- The code in this repository: the `bromigos` command, the installer, the ISO, the
  desktop's scripts, the live layer and the panels (widgets).
- The bromigOS packages and their signatures. If you think the package signing key is
  compromised, say so first in your report.
- VECTOR, the desktop's AI assistant, lives in
  [bromigos-org/vector](https://github.com/bromigos-org/vector). Report a problem with
  him the same way.

Problems in Arch Linux's own packages belong to Arch. Report them to the
[Arch Linux security team](https://security.archlinux.org/). Problems in other software
that bromigOS installs belong to that software's project.

## Which versions get fixes

A fix ships in the next release on each [channel](manual/src/update-and-rollback.md#channels).
Older releases don't get separate fixes. To get a fix, update with `bromigos update`.

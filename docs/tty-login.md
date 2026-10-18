# Text console login banner

The text console login has a green bromigOS header and a short list of commands to
use after signing in. The usual username and password prompts still come from
agetty and login. No authentication code is replaced.

`bromigos-settings` installs
[`settings/console/60-bromigos.issue`](../settings/console/60-bromigos.issue) as
`/usr/lib/issue.d/60-bromigos.issue`. It depends on `util-linux>=2.41`. Starting with
that version, agetty reads `/usr/lib/issue.d` even when `/etc/issue` exists. This
keeps the banner in a package-owned path without replacing the machine's existing
issue message or overriding systemd's getty service. The behaviour is documented in
[agetty's upstream manual](https://kernel.googlesource.com/pub/scm/utils/util-linux/util-linux/+/refs/tags/v2.42.4/term-utils/agetty.8.adoc).

The banner uses ASCII characters and agetty's `lightgreen`, `bold` and `reset`
escapes. It needs neither a graphical terminal nor a Nerd Font. Colour is reset
before the hints and login prompt. The text is at most 72 columns wide.

An administrator's `--noissue` option suppresses it. An explicit `--issue-file`
list replaces agetty's default search locations, so a custom getty command must
include the banner if it is wanted. There is no install hook to reload getty or
interrupt an existing session. The next fresh getty reads the file; a reboot is
enough. Other getty services that use the standard issue paths may show it too.

## Testing

```sh
python -m unittest discover -s settings/console/tests
```

The native test runs only `agetty --show-issue` with a private pseudo-terminal and
captured output. It checks the actual escape expansion and visible text. No login
process or workstation text console is opened. A separate check rejects font
icons, control bytes and escape codes that could expose machine details.

The user's preview and instructions are in
[Text console login](../manual/src/console-login.md).

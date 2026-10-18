# Text console login

`60-bromigos.issue` adds a green bromigOS banner above the usual text console login
prompt. It uses ASCII text and agetty's named colour escapes, so it works with the
console's bitmap fonts.

`bromigos-settings` installs it as `/usr/lib/issue.d/60-bromigos.issue` and requires
`util-linux>=2.41`. That version reads package issue files even when `/etc/issue`
exists. No getty service override or authentication configuration is needed.

The banner gives commands to use after signing in. It does not run those commands,
show private machine details or replace the username and password prompts.

See [the contributor notes](../../docs/tty-login.md) for the upstream behaviour and
[the manual](../../manual/src/console-login.md) for what a user sees.

## Test without a real console

```sh
python -m unittest discover -s settings/console/tests
```

The render test gives `agetty --show-issue` a disposable pseudo-terminal for its
input and captures its output. It never opens a workstation console, starts a login
process, changes terminal settings or calls a service manager.

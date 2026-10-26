# Text console login

Text consoles show a green bromigOS banner above the usual login prompt. Sign in
with your normal username and password. The password stays hidden as you type.

```text
  +------------------------------------------------------+
  |  bromigOS                               TEXT CONSOLE |
  +------------------------------------------------------+

  Sign in with your username and password.

  After signing in:
    bromigos console status   Check the console font
    bromigos power menu       Restart or shut down
```

The banner uses ordinary text characters, so it works with the console's font.
If the text is too small, see
[Make text consoles readable](shell.md#make-text-consoles-readable).

After signing in, `bromigos power menu` opens a keyboard menu for restarting or
shutting down. It asks you to confirm the selected action.

Your password also unlocks your keyring, where bromigOS keeps your sign-ins. So a desktop
you start from the console doesn't ask for it again. See
[Your keyring](bromigos-account.md#your-keyring).

The `bromigos-settings` package supplies the banner. It appears the next time the
console login starts, including after a reboot. Your existing issue message may
also appear above it. A custom getty configuration can hide or replace issue
messages.

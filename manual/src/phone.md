# Pair your phone

With the BRODEC app on your phone paired to this computer, you can reach it from anywhere.
The welcome tour's **Pair your phone** step sets it up, and you can do it again any time.

## Get BRODEC

BRODEC is on Google Play (`org.bromigos.brodec`): the tour shows a QR code that opens it.
BRODEC for iPhone is coming.

## Pair

1. **BRODEC's helper.** Pairing uses BRODEC's machine helper, which comes in the optional
   `brodec-desktop` package. The step explains it and installs it when you agree, the
   usual way: the system asks for your password in its own window. No terminal.
2. **Scan the code.** The step shows a big QR code and a short code. In BRODEC, open
   LAB › MACHINES › **ADD MACHINE** and scan the QR, or type the short code.
3. **Confirm on your phone.** BRODEC shows this computer's name and asks you to confirm.
   When it's done, the step ticks ✓.

![Pair your phone: Google Play's QR code, the pairing code and what the phone can do](images/welcome-tour-phone.webp)

If your lab has a VECTOR bridge that isn't paired yet, the step offers to pair it too, the
same way.

## What your phone can do then

- Chat with VECTOR, from anywhere.
- Approve the fixes VECTOR proposes for this computer.
- Restart, shut down or update this computer.
- Open chat-style terminal sessions on it.

Nothing runs on this computer without your say-so: everything travels end-to-end
encrypted, from your account only, and the serious requests ask for your fingerprint on
the phone.

## For power users

The helper is `brodec-machine`, a user service (`brodec-machine.service`):

| Command | What it does |
|---|---|
| `brodec-machine pair` | Shows the pairing code and its QR in the terminal, until it's paired |
| `brodec-machine status` | Paired with whom, the switch, jobs |
| `sudo brodec-machine enroll` | Allows a phone that asked to send jobs: the machine owner's own step, at the machine |
| `brodec-machine off` | STOP ALL: every job on this machine stops |

While it waits, the agent writes the code to `~/.local/share/brodec-machine/pair-code.json`
(`user_code`, the QR's text `qr`, `fingerprint`, `expires_at_ms`); the tour draws its QR
from that file. Once paired it writes `~/.local/share/brodec-machine/pairing.json`. Pairing
is the Bromigos account's device flow, approved from the phone with `kind: "machine"`; the
phone checks the machine's key against the fingerprint in the QR, so one scan verifies
both ways. A code runs out after a few minutes and a new one follows by itself.

---
name: __NAME__
description: How to read this machine's load average and say whether it's busy.
when_to_use: When the user asks whether the computer is busy, slow or working hard.
---

# Reading the load

1. Read the load average (the system panel, or `cat /proc/loadavg`): three numbers,
   the runnable tasks averaged over 1, 5 and 15 minutes.
2. Compare them with the CPU count (`nproc`): below it the machine has room; near it,
   it's busy; well above it, things wait.
3. Say which way it's heading: the 1-minute figure above the 15-minute one means it's
   getting busier.
4. Name what's working if asked: `ps -eo pid,comm,%cpu --sort=-%cpu | head`.

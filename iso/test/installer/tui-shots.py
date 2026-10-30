#!/usr/bin/env python3
"""Every step of the text installer as pictures (SVG, and PNG with rsvg-convert), on the
recorded disks with the fake install: once as a desktop alongside Windows, once as bromigOS
Server (its SSH step), and the failure screen. docs/iso.md, "Testing it".

  tui-shots.py OUTDIR [--colors truecolor|16]
"""
import asyncio
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
out = os.path.abspath(sys.argv[1])
colors = sys.argv[sys.argv.index("--colors") + 1] if "--colors" in sys.argv else "truecolor"
os.environ["BROMIGOS_COLORS"] = colors
os.environ.setdefault("BROMIGOS_INSTALLER_FAKE_DELAY", "0.6")
sys.argv = [sys.argv[0]]
sys.path.insert(0, HERE)
import test_tui  # noqa: E402,F401  (the recorded disks, the fake store and back end)
os.environ["BROMIGOS_INSTALLER_FAKE_DELAY"] = "0.6"     # slow enough to catch the install mid-way
from tuidrive import drive  # noqa: E402
from bromigos_installer import tui  # noqa: E402


async def run(plan, tag, finish=True, fail=False):
    if fail:
        os.environ["BROMIGOS_INSTALLER_FAKE_FAIL"] = "1"
    app = tui.Installer()
    async with app.run_test(size=(120, 40)) as pilot:
        plan = dict(plan, shots=os.path.join(out, tag))
        await drive(app, pilot, plan)
        if finish:
            await pilot.press("ctrl+n")
            await pilot.pause(2.2)
            app.save_screenshot(os.path.join(out, tag, "tui-install.svg"))
            for _ in range(200):
                if app.step == "done":
                    break
                await pilot.pause(0.05)
            await pilot.pause(0.3)
            app.save_screenshot(os.path.join(out, tag, "tui-done.svg" if not fail else "tui-failed.svg"))
    os.environ.pop("BROMIGOS_INSTALLER_FAKE_FAIL", None)


async def main():
    key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyForTheInstallerTestsOnly tester@lab"
    await run({"mode": "alongside", "gib": 64}, f"{colors}-desktop")
    await run({"edition": "server", "mode": "erase", "disk_index": 1, "ssh_key": key}, f"{colors}-server")
    await run({"mode": "erase", "disk_index": 1}, f"{colors}-failed", fail=True)
    for root, _, files in os.walk(out):
        for f in files:
            if f.endswith(".svg"):
                src = os.path.join(root, f)
                subprocess.run(["rsvg-convert", "-w", "1500", src, "-o", src[:-4] + ".png"])
                print(src[:-4] + ".png")


asyncio.run(main())

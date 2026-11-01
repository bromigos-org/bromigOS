"""An answer file installed by itself, as from a USB stick (iso/test.sh answer-install; run as
root in the live system with BROMIGOS_ANSWERS=FILE): the text installer opens on its countdown,
installs, and ends on Done. Prints the install's stages; exits 0 when it's installed, else
says why (the answer file's problems, or where the install stopped)."""
import asyncio
import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(HERE, "../../../lib"))
for lib in (os.path.join(HERE, "../../profile/airootfs/usr/local/lib/bromigos-iso"), "/usr/local/lib/bromigos-iso"):
    if os.path.isdir(os.path.join(lib, "bromigos_installer")):
        sys.path.insert(0, lib)
        break


async def main(timeout=7200):
    from bromigos_installer import tui
    app = tui.Installer()
    async with app.run_test(size=(120, 42)) as pilot:
        await pilot.pause(2)
        if app.step != "auto":
            print("not unattended: the installer asks instead:", str(app.query_one("#error").render()), flush=True)
            return 1
        print("the countdown is on: installing by itself", flush=True)
        last = None
        for _ in range(int(timeout / 2)):
            if app.step == "done":
                break
            await pilot.pause(2)
            if app.step == "welcome":
                print("it stopped asking instead:", str(app.query_one("#error").render()), flush=True)
                return 1
            now = str(app.status.render()) if hasattr(app, "status") else ""
            if now != last:
                print(f"  {getattr(getattr(app, 'bar', None), 'progress', 0):3.0f}%  {now}", flush=True)
                last = now
        print("ended on", app.step, "installed" if app.done is True else f"NOT installed: {app.done}", flush=True)
        return 0 if app.done is True else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

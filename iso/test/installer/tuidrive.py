"""Drives the text installer through its steps by keys (Textual's Pilot, headless), as a
person would: the unit tests use it on recorded disks (test_tui.py), and the test VM on its
real disks with the real install (iso/test.sh tui-install; run as root in the live system):

  python3 tuidrive.py PLAN.json      PLAN: {mode: erase|alongside, gib, disk_index, encrypt,
                                     separate, edition, user, password, hostname, full_name,
                                     ssh, shots}; prints the step it ended on and the install's
                                     last words; exits 0 when it's installed
"""
import asyncio
import json
import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(HERE, "../../../lib"))          # bromigos_textual, from this checkout
for lib in (os.path.join(HERE, "../../profile/airootfs/usr/local/lib/bromigos-iso"), "/usr/local/lib/bromigos-iso"):
    if os.path.isdir(os.path.join(lib, "bromigos_installer")):
        sys.path.insert(0, lib)
        break


async def wait_for(app, pilot, selector, seconds=30):
    """Until selector is on screen: redraws are asynchronous, and a VM can be slow."""
    for _ in range(int(seconds * 10)):
        if app.query(selector):
            return app.query_one(selector)
        await pilot.pause(0.1)
    raise AssertionError(f"{selector} never appeared (step {app.step})")


async def type_text(pilot, text):
    for ch in text:
        await pilot.press({" ": "space", "-": "minus", "_": "underscore", ".": "full_stop", "/": "slash"}.get(ch, ch))


async def drive(app, pilot, plan):
    """Through the steps by keyboard: plan = {edition, disk_index, mode, gib, encrypt, separate}."""
    shots = []

    async def shot(name):
        await pilot.pause()
        shots_dir = plan.get("shots") or os.environ.get("BROMIGOS_INSTALLER_SHOTS")
        if shots_dir:
            os.makedirs(shots_dir, exist_ok=True)
            app.save_screenshot(os.path.join(shots_dir, f"tui-{name}.svg"))
        shots.append(name)

    await pilot.pause(0.3)
    assert app.step == "welcome"
    await shot("welcome")
    await pilot.press("ctrl+n")
    if app.step == "checks":                 # only when this computer has something to say
        await shot("checks")
        await pilot.press("ctrl+n")
    if "edition" in app.steps():
        assert app.step == "edition", app.step
        if plan.get("edition", "desktop") != "desktop":
            app.query_one(f"#ed-{plan['edition']}").value = True
            await pilot.pause()
        await shot("edition")
        await pilot.press("ctrl+n")
    assert app.step == "keyboard", app.step
    await pilot.press("tab")
    await type_text(pilot, "hello")
    await shot("keyboard")
    await pilot.press("ctrl+n")
    assert app.step == "disk", app.step
    for _ in range(50):
        if app.probe is not None:
            break
        await pilot.pause(0.1)
    await app.show("disk")
    await pilot.pause()
    disks = app.probe["disks"]
    target = disks[plan.get("disk_index", 0)]
    app.query_one(f"#disk-{plan.get('disk_index', 0)}").value = True
    await pilot.pause()
    # picking a disk redraws its choices: wait until they're there (a slow VM takes longer
    # than one pause), then until the redraw is done
    await wait_for(app, pilot, f"#mode-{plan['mode']}")
    async with app.redraw:
        pass
    app.query_one(f"#mode-{plan['mode']}").value = True
    await pilot.pause(0.3)
    async with app.redraw:
        pass
    if plan["mode"] == "reinstall" and app.query("#old_passphrase"):
        app.query_one("#old_passphrase").value = plan.get("old_passphrase") or plan.get("password", "")
    if plan.get("gib") and plan["mode"] == "alongside":
        split = app.query_one("#split")
        split.focus()
        await pilot.press("home")
        for _ in range(plan["gib"] - 20):
            await pilot.press("right")
    await shot("disk")
    await pilot.press("ctrl+n")
    assert app.step == "user", (app.step, str(app.query_one("#error").render()))
    app.query_one("#full_name").focus()
    await type_text(pilot, plan.get("full_name", "Alex Rivera"))
    if plan.get("user"):
        app.query_one("#user").value = plan["user"]
        app.a["user_edited"] = True
    if plan.get("hostname"):
        app.query_one("#hostname").value = plan["hostname"]
        app.a["host_edited"] = True
    pw = plan.get("password", "correct-horse")
    app.query_one("#password").focus()
    await type_text(pilot, pw)
    app.query_one("#password2").focus()
    await type_text(pilot, pw)
    await shot("user")
    await pilot.press("ctrl+n")
    if plan["mode"] == "reinstall":            # the disk's encryption stays as it is: no step for it
        if app.step == "ssh":
            app.query_one("#ssh").value = plan.get("ssh", True)
            await pilot.pause(0.2)
            if plan.get("ssh_key") and app.a.get("ssh"):
                app.query_one("#pasted-key").value = plan["ssh_key"]
            await pilot.press("ctrl+n")
        assert app.step == "summary", (app.step, str(app.query_one("#error").render()))
        await shot("summary")
        return target, shots
    assert app.step == "encryption", (app.step, str(app.query_one("#error").render()))
    if not plan.get("encrypt", True):
        app.query_one("#encrypt").value = False
    if plan.get("separate"):
        app.query_one("#separate").value = True
        await pilot.pause()
        app.query_one("#passphrase").focus()
        await type_text(pilot, "disk-pass")
        app.query_one("#passphrase2").focus()
        await type_text(pilot, "disk-pass")
    await shot("encryption")
    await pilot.press("ctrl+n")
    if "ssh" in app.steps():
        assert app.step == "ssh", app.step
        app.query_one("#ssh").value = plan.get("ssh", True)
        await pilot.pause(0.2)
        if plan.get("ssh_key") and app.a.get("ssh"):
            app.query_one("#pasted-key").value = plan["ssh_key"]
        if plan.get("ssh_password"):
            app.query_one("#ssh-pw").value = True
        await shot("ssh")
        await pilot.press("ctrl+n")
    assert app.step == "summary", (app.step, str(app.query_one("#error").render()))
    await shot("summary")
    return target, shots



async def install(plan, timeout=7200):
    from bromigos_installer import tui
    app = tui.Installer()
    async with app.run_test(size=(120, 42)) as pilot:
        await drive(app, pilot, plan)
        await pilot.press("ctrl+n")
        last = None
        for _ in range(int(timeout / 2)):
            if app.step == "done":
                break
            await pilot.pause(2)
            now = str(app.status.render()) if hasattr(app, "status") else ""
            if now != last:
                print(f"  {app.bar.progress:3.0f}%  {now}", flush=True)
                last = now
        shots_dir = plan.get("shots")
        if shots_dir:
            app.save_screenshot(os.path.join(shots_dir, "tui-done.svg"))
        return app.step, app.done


if __name__ == "__main__":
    plan = json.load(open(sys.argv[1]))
    step, done = asyncio.run(install(plan))
    print("ended on", step, "installed" if done is True else f"NOT installed: {done}")
    sys.exit(0 if done is True else 1)

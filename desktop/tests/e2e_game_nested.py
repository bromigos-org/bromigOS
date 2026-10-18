#!/usr/bin/env python3
"""Game mode in a private HOME, D-Bus and nested Hyprland. No real logind/input devices.
The logind inhibitor is a pipe-reading fixture; the compositor, dunst and key client
are real. The fixture records that an independent inhibitor lives until mode ends.
"""
import json
import os
import re
from pathlib import Path
import signal
import subprocess
import sys
import time

from e2e_keys_nested import Nest, Run, REPO, wait_for

CLIENT = '''import gi,json,os
from pathlib import Path
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk,Gdk,GLib
GLib.set_prgname("game-fixture.exe")
win=Gtk.Window(title="Game input test")
win.set_default_size(500,300)
win.add(Gtk.Label(label="Game input test"))
def key(w,e):
    with open(os.path.join(os.environ["HOME"],"keys.jsonl"),"a") as f:
        f.write(json.dumps({"key":Gdk.keyval_name(e.keyval),"state":int(e.state)})+"\\n")
win.connect("key-press-event",key)
win.connect("destroy",Gtk.main_quit)
win.show_all()
Gtk.main()
'''


def private_bus(n):
    env = dict(n.base, PATH="/usr/bin")
    env.pop("DBUS_SESSION_BUS_ADDRESS", None)
    bus = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"],
                           env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
    n.procs.append(bus)
    n.base["DBUS_SESSION_BUS_ADDRESS"] = bus.stdout.readline().decode().strip()


def game(n, *args, env=None):
    p = subprocess.run(["bromigos", "game", *args, "--json"], env=env or n.env,
                       capture_output=True, text=True, timeout=20)
    if p.returncode:
        raise RuntimeError(p.stderr or p.stdout)
    return json.loads(p.stdout)


def bar_item(n):
    text=Path(REPO,"desktop/waybar/config.jsonc").read_text()
    config=json.loads(re.sub(r"^\s*//.*$", "", text, flags=re.M))
    command=config["custom/game"]["exec"]
    result=subprocess.run(command,shell=True,env=n.env,capture_output=True,text=True,timeout=15)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def start_mode(n):
    # No host logind access: the fixture lives exactly as long as the helper's pipe.
    inhibitor = Path(n.stubs, "systemd-inhibit")
    inhibitor.write_text('#!/usr/bin/python3\nimport os,sys\nfrom pathlib import Path\np=Path(os.environ["HOME"])/"inhibited"\np.touch()\nsys.stdin.buffer.read()\np.unlink()\n')
    inhibitor.chmod(0o755)
    n.env["BROMIGOS_LIB_BIN"] = os.path.join(REPO, "desktop/bin")
    # Autostart --watch was stubbed by Nest. Own this helper for exact cleanup.
    helper = subprocess.Popen([sys.executable, os.path.join(REPO, "desktop/bin/bromigos-game"), "--watch"],
                              env=n.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    n.procs.append(helper)
    if not wait_for(lambda: Path(n.run, "bromigos-game.sock").exists()):
        raise RuntimeError("game helper did not start")
    return helper


def scenarios(n, r):
    dunst = subprocess.Popen(["/usr/bin/dunst"], env=n.env, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
    n.procs.append(dunst)
    wait_for(lambda: subprocess.run(["dunstctl", "is-paused"], env=n.env, capture_output=True).returncode == 0)
    helper = start_mode(n)
    fixture = Path(n.tmp, "client.py")
    fixture.write_text(CLIENT)
    client = subprocess.Popen([sys.executable, str(fixture)], env=n.env, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, start_new_session=True)
    n.procs.append(client)
    r.check("test client focused", wait_for(lambda: "Game input test" in n.ctl("activewindow")))
    r.check("no config errors", n.ctl("configerrors") == "", n.ctl("configerrors"))
    n.kb.combo("SUPER + W")
    r.check("normal desktop binding fires", wait_for(lambda: bool(n.widgets_log())))
    before = len(n.widgets_log())
    r.check("automatic mode starts off", not game(n, "status")["auto"])
    n.kb.combo("SUPER + CTRL + G")
    r.check("keyboard enters game submap", wait_for(lambda: n.submap() == "bromigos-game"))
    r.check("bar shows GAME MODE",bar_item(n)["text"]=="GAME MODE")
    r.check("idle inhibitor held", Path(n.home, "inhibited").exists())
    r.check("notifications paused", subprocess.check_output(["dunstctl", "is-paused"],env=n.env,text=True).strip()=="true")
    binds = json.loads(n.ctl("binds", "-j"))
    active = [b for b in binds if b.get("submap") == "bromigos-game" or b.get("submap_universal") in (True, "true")]
    r.check("only the escape binding remains", len(active) == 1, active)
    Path(n.home, "keys.jsonl").write_text("")
    for combo in ("SUPER + W", "ALT + J", "CTRL + A", "F1", "G"):
        n.kb.combo(combo)
    def keys():
        return [json.loads(x)["key"].lower() for x in Path(n.home,"keys.jsonl").read_text().splitlines()]
    r.check("desktop keys and game keys reach focused client", wait_for(lambda: all(k in keys() for k in ("w","j","a","f1","g"))), keys())
    r.check("desktop binding did not fire", len(n.widgets_log()) == before)
    n.kb.combo("CTRL + SHIFT + F12")
    r.check("escape resets shortcuts", wait_for(lambda: n.submap() == "default"))
    r.check("escape restores notifications", wait_for(lambda: subprocess.check_output(["dunstctl","is-paused"],env=n.env,text=True).strip()=="false"))
    r.check("escape releases inhibitor", wait_for(lambda: not Path(n.home,"inhibited").exists()))
    r.check("bar indicator clears",bar_item(n)["text"]=="")
    n.kb.combo("SUPER + W")
    r.check("desktop binding works again", wait_for(lambda: len(n.widgets_log()) > before))
    subprocess.run(["dunstctl","set-paused","true"],env=n.env,check=True)
    r.check("CLI on", game(n,"on")["on"])
    r.check("CLI on is idempotent", game(n,"on")["on"])
    r.check("CLI toggle leaves", not game(n,"toggle")["on"])
    r.check("pre-existing DND restored exactly", subprocess.check_output(["dunstctl","is-paused"],env=n.env,text=True).strip()=="true")
    subprocess.run(["dunstctl","set-paused","false"],env=n.env,check=True)
    game(n,"on")
    tty = dict(n.env)
    for key in ("HYPRLAND_INSTANCE_SIGNATURE","DISPLAY","WAYLAND_DISPLAY","DBUS_SESSION_BUS_ADDRESS"):
        tty.pop(key,None)
    r.check("TTY/SSH off discovers session", not game(n,"off",env=tty)["on"] and n.submap()=="default")
    game(n,"on")
    n.ctl("dispatch", 'hl.dsp.submap("reset")')
    r.check("external submap reset restores desktop", wait_for(lambda: not Path(n.run,"bromigos-game-on.json").exists()))
    game(n,"auto","on")
    n.ctl("dispatch", 'hl.dsp.window.fullscreen()')
    r.check("automatic mode enters for focused fullscreen game",wait_for(lambda:n.submap()=="bromigos-game"))
    n.kb.combo("CTRL + SHIFT + F12")
    r.check("escape leaves automatic mode",wait_for(lambda:n.submap()=="default"))
    time.sleep(0.6)
    r.check("automatic mode respects manual escape",not game(n,"status")["on"])
    n.ctl("dispatch", 'hl.dsp.window.fullscreen()')
    time.sleep(0.4)
    n.ctl("dispatch", 'hl.dsp.window.fullscreen()')
    r.check("fullscreen change allows automatic re-entry",wait_for(lambda:n.submap()=="bromigos-game"))
    n.ctl("dispatch", 'hl.dsp.window.fullscreen()')
    r.check("leaving fullscreen restores desktop",wait_for(lambda:n.submap()=="default"))
    game(n,"auto","off")
    game(n,"on")
    helper.kill(); helper.wait()
    r.check("helper crash releases inhibitor", wait_for(lambda: not Path(n.home,"inhibited").exists()))
    r.check("CLI off recovers stale socket and snapshot", not game(n,"off")["on"] and n.submap()=="default")
    # The replacement helper exits automatically when the nested session ends.
    r.check("DND restored after crash", subprocess.check_output(["dunstctl","is-paused"],env=n.env,text=True).strip()=="false")


def side_effects(n, r):
    """The checkout's real panels and wallpaper, with isolated readings and no audio."""
    share=Path(n.tmp,"share")
    (share/"widgets").mkdir(exist_ok=True)
    (share/"widgets/layout.json").symlink_to(Path(REPO,"widgets/layout.json"))
    env=dict(n.env,BROMIGOS_WIDGETS_DEMO="1",BROMIGOS_HOMELAB="/nonexistent",
             PYTHONPATH=os.pathsep.join([os.path.join(REPO,"lib"),os.path.join(REPO,"desktop/lib")]))
    log=open(Path(n.tmp,"widgets.log"),"w")
    widgets=subprocess.Popen([sys.executable,os.path.join(REPO,"widgets/bromigos-widgets")],env=env,
                             stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    n.procs.append(widgets)
    r.check("real widgets mapped",wait_for(lambda:n.layer("bromigos-widgets"),15))
    def count():
        data=json.loads(n.ctl("layers","-j") or "{}")
        return sum(1 for mon in data.values() for layers in mon.get("levels",{}).values()
                   for layer in layers if layer.get("namespace")=="bromigos-widgets")
    subprocess.run([sys.executable,os.path.join(REPO,"widgets/bromigos-widgets"),"toggle","network"],
                   env=env,capture_output=True,timeout=5)
    time.sleep(0.3)
    before=count()
    cfg=Path(n.tmp,"live.toml")
    cfg.write_text('[general]\nfps=5\nfps_covered=5\nallow_software=true\n[events]\nintercept_on_login=false\nintercept_on_unlock=false\nlock_emblem=false\n[codec]\nenabled=false\n[sounds]\nenabled=false\n[tv]\nenabled=false\n')
    env.update(BROMIGOS_LIVE_CONFIG=str(cfg),BROMIGOS_LIVE_VIRT="none",LIBGL_ALWAYS_SOFTWARE="1",
               __EGL_VENDOR_LIBRARY_FILENAMES="/usr/share/glvnd/egl_vendor.d/50_mesa.json")
    live_log=open(Path(n.tmp,"live.log"),"w")
    live=subprocess.Popen([sys.executable,"-m","live.app"],cwd=os.path.join(REPO,"live"),env=env,
                          stdout=live_log,stderr=subprocess.STDOUT,start_new_session=True)
    n.procs.append(live)
    def live_state():
        import socket
        try:
            with socket.socket(socket.AF_UNIX) as conn:
                conn.settimeout(2);conn.connect(str(Path(n.run,"bromigos-live.sock")))
                conn.sendall(b"state")
                return conn.recv(65536).decode()
        except OSError:
            return ""
    r.check("real wallpaper started",wait_for(lambda:bool(live_state()),30))
    previous_live=live_state().split(" measured=",1)[0]
    game(n,"on")
    r.check("game mode hides real widgets",wait_for(lambda:count()==0))
    r.check("game mode pauses real wallpaper",wait_for(lambda:"background paused target=0fps" in live_state()),live_state()[:160])
    game(n,"off")
    r.check("widget visibility restored exactly",wait_for(lambda:count()==before),f"{count()} vs {before}")
    r.check("wallpaper coverage behaviour restored",wait_for(lambda:live_state().split(" measured=",1)[0]==previous_live))
    settings=Path(n.tmp,"game-settings.png")
    rendered=subprocess.run([sys.executable,os.path.join(REPO,"desktop/settings/bromigos-settings"),
                             "--render",str(settings),"--page","game"],env=env,capture_output=True,
                            text=True,timeout=40)
    r.check("Settings Playing games page renders",rendered.returncode==0 and settings.exists(),rendered.stderr[-600:])



def main():
    n, r = Nest("--keep" in sys.argv), Run()
    try:
        private_bus(n)
        n.base["KWIN_COMPOSE"] = "O2"
        n.base["BROMIGOS_LIB_BIN"] = os.path.join(REPO, "desktop/bin")
        n.start()
        scenarios(n,r)
        side_effects(n,r)
    finally:
        n.stop()
        if n.keep:
            print("kept:",n.tmp)
    return int(any(not ok for _,ok,_ in r.results))


if __name__ == "__main__":
    sys.exit(main())

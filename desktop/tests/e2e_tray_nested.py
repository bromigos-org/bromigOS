#!/usr/bin/env python3
"""A real GTK XEmbed icon, bridge and Waybar in a private nested session.
Checks embedding, SNI publication, Waybar acceptance and right-click forwarding.
The GTK 2 fixture uses XEmbed button events, the same bridge path Wine uses.
Needs gtk2 as well as the nested harness dependencies.
"""
import os
import json
import time
from pathlib import Path
import subprocess
import sys

from e2e_keys_nested import Nest, Run, REPO, wait_for
from e2e_game_nested import private_bus
from vptr import VirtualPointer, RIGHT

ICON = r'''import ctypes as C
import os
from pathlib import Path
G=C.CDLL("libgtk-x11-2.0.so.0")
P=C.c_void_p
U=C.c_uint

def function(name,result,args):
    fn=getattr(G,name);fn.restype=result;fn.argtypes=args
    return fn
init=function("gtk_init",None,[P,P])
new_pix=function("gdk_pixbuf_new",P,[C.c_int,C.c_int,C.c_int,C.c_int,C.c_int])
fill=function("gdk_pixbuf_fill",None,[P,U])
new_icon=function("gtk_status_icon_new_from_pixbuf",P,[P])
visible=function("gtk_status_icon_set_visible",None,[P,C.c_int])
embedded=function("gtk_status_icon_is_embedded",C.c_int,[P])
menu_new=function("gtk_menu_new",P,[])
item_new=function("gtk_menu_item_new_with_label",P,[C.c_char_p])
append=function("gtk_menu_shell_append",None,[P,P])
show=function("gtk_widget_show_all",None,[P])
popup_menu=function("gtk_menu_popup",None,[P,P,P,P,P,U,U])
connect=function("g_signal_connect_data",C.c_ulong,[P,C.c_char_p,P,P,P,U])
timeout=function("g_timeout_add",U,[U,P,P])
main=function("gtk_main",None,[])
log=Path(os.environ["HOME"])/"tray-client.log"
def record(text):
    with log.open("a") as f: f.write(text+"\n")
init(None,None)
pix=new_pix(0,1,8,22,22);fill(pix,0x33aaeeff)
icon=new_icon(pix);visible(icon,1)
@C.CFUNCTYPE(None,P,U,U,P)
def popup(icon,button,when,_data):
    record("menu")
    menu=menu_new();append(menu,item_new(b"XEmbed menu works"));show(menu)
    popup_menu(menu,None,None,C.cast(G.gtk_status_icon_position_menu,P),icon,button,when)
@C.CFUNCTYPE(C.c_int,P)
def check(_data):
    record("embedded" if embedded(icon) else "unembedded")
    return 1
connect(icon,b"popup-menu",C.cast(popup,P),None,None,0)
timeout(250,C.cast(check,P),None)
main()
'''


def main():
    n,r=Nest("--keep" in sys.argv),Run()
    pointer=None
    try:
        private_bus(n)
        n.base["KWIN_COMPOSE"]="O2"
        conf=Path(n.lua).read_text().replace('xwayland = { enabled = false }','xwayland = { enabled = true }')
        Path(n.lua).write_text(conf)
        n.start()
        r.check("no config errors",n.ctl("configerrors")=="",n.ctl("configerrors"))
        # The Xwayland display belongs to the nested compositor, never inherit DISPLAY.
        def display():
            out=n.ctl("env")
            return next((line.split("=",1)[1] for line in out.splitlines() if line.startswith("DISPLAY=")),None)
        nested_display=wait_for(display)
        if not nested_display:
            # Lua API exports the environment through the repl on current Hyprland.
            value=n.ctl("repl", 'print(os.getenv("DISPLAY"))').strip()
            if value.startswith(":"):
                nested_display=value
        if not nested_display:
            raise RuntimeError("nested Xwayland did not export DISPLAY")
        n.env["DISPLAY"]=nested_display
        n.env["XDG_SESSION_TYPE"]="wayland"
        config=Path(n.tmp,"waybar.json")
        config.write_text('{"layer":"top","height":34,"modules-right":["tray"],"tray":{"icon-size":22,"spacing":4}}')
        barlog=open(Path(n.tmp,"waybar.log"),"w")
        bar=subprocess.Popen(["/usr/bin/waybar","-c",str(config),"-l","debug"],env=n.env,
                             stdout=barlog,stderr=subprocess.STDOUT,start_new_session=True)
        n.procs.append(bar)
        r.check("Waybar mapped in nested session",wait_for(lambda:n.layer("waybar")))
        bridge=subprocess.Popen(["/usr/bin/xembedsniproxy"],env=dict(n.env,QT_LOGGING_RULES="*.debug=true"),stdout=open(Path(n.tmp,"bridge.log"),"w"),
                                stderr=subprocess.STDOUT,start_new_session=True)
        n.procs.append(bridge)
        fixture=Path(n.tmp,"tray_client.py");fixture.write_text(ICON)
        client=subprocess.Popen([sys.executable,str(fixture)],env=dict(n.env,GDK_BACKEND="x11"),
                                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        n.procs.append(client)
        def logged(text):
            p=Path(n.home,"tray-client.log")
            return p.exists() and text in p.read_text().splitlines()
        r.check("XEmbed client docked instead of floating",wait_for(lambda:logged("embedded")))
        def items():
            p=subprocess.run(["gdbus","call","--session","--dest","org.kde.StatusNotifierWatcher",
                              "--object-path","/StatusNotifierWatcher","--method","org.freedesktop.DBus.Properties.Get",
                              "org.kde.StatusNotifierWatcher","RegisteredStatusNotifierItems"],env=n.env,
                             capture_output=True,text=True,timeout=5)
            return p.stdout
        r.check("bridge publishes a StatusNotifierItem",wait_for(lambda:"StatusNotifierItem" in items()),items())
        r.check("Waybar accepted the tray item",wait_for(lambda:"SNI tray id:" in Path(n.tmp,"waybar.log").read_text()),
                Path(n.tmp,"waybar.log").read_text()[-800:])
        time.sleep(1)  # the bridge captures the first icon paint after 500 ms
        subprocess.run(["grim",str(Path(n.tmp,"tray.png"))],env=n.env,capture_output=True)
        mon=json.loads(n.ctl("monitors","-j"))[0]
        size=(round(mon["width"]/mon["scale"]),round(mon["height"]/mon["scale"]))
        pointer=VirtualPointer(os.path.join(n.run,"wayland-1"),*size)
        pointer.click(RIGHT,at=(size[0]-14,17))
        subprocess.run(["grim",str(Path(n.tmp,"tray-after.png"))],env=n.env,capture_output=True)
        r.check("Waybar right-click reaches XEmbed menu",wait_for(lambda:logged("menu")),n.ctl("cursorpos"))
        clients=n.ctl("clients","-j")
        r.check("no standalone tray client window",'"title": "XEmbed fixture"' not in clients)
    finally:
        if pointer: pointer.close()
        n.stop()
        if n.keep: print("kept:",n.tmp)
    return int(any(not ok for _,ok,_ in r.results))


if __name__=="__main__":
    sys.exit(main())

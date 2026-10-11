"""The actual Lua controller and mpv IPC bridge, with null video/audio and a sandbox palette."""
import json
import os
import shutil
import socket
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
try:
    from live import tvfull, glkit
except ImportError:
    tvfull = glkit = None


def wait(fn, timeout=6):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        value=fn()
        if value: return value
        time.sleep(.05)
    return fn()


@unittest.skipUnless(glkit is not None and shutil.which("mpv") and shutil.which("ffmpeg"), "needs PyOpenGL, mpv and ffmpeg")
class Full(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="den-full-test-");self.addCleanup(self.tmp.cleanup)
        self.patch=mock.patch.dict(os.environ,XDG_RUNTIME_DIR=self.tmp.name);self.patch.start();self.addCleanup(self.patch.stop)
        palette=self.tmp.name+"/theme.json"
        with open(palette,"w") as f: json.dump(dict(colors=glkit.T.WICK),f)
        patch=mock.patch.object(glkit.T,"PATH",palette);patch.start();self.addCleanup(patch.stop)
        self.theme=palette;glkit.T.version(0.)
        clip=self.tmp.name+"/clip.mp4"
        __import__("subprocess").run(["ffmpeg","-v","error","-y","-f","lavfi","-i","color=size=64x64:rate=1",
            "-t","30","-c:v","libx264","-preset","ultrafast",clip],check=True)
        self.tv=types.SimpleNamespace(screens={"big":dict(volume=40,sound=True)},motion="full",overrides={},
                                     _tls_ca=lambda:None,feedback=lambda *a:None)
        def changed(screen,on,volume,from_full=False): self.tv.screens[screen].update(volume=volume,sound=on)
        self.tv.set_sound=changed
        self.session=tvfull.Session(self.tv,"big",dict(url=clip,title="Test Card",headers={},start=0),
                                   extra=["--vo=null","--ao=null","--fs=no","--hwdec=no"])
        self.addCleanup(self.close_session)
        self.assertTrue(wait(lambda:os.path.exists(self.session.sock_path)))
        self.assertTrue(wait(lambda:self.query("get_property","user-data/den/controller")))

    def close_session(self):
        self.session.close()
        self.session.proc.wait(timeout=5)
        self.session.thread.join(timeout=5)
        self.assertFalse(self.session.thread.is_alive(), "the IPC worker must finish before its sandbox is removed")

    def query(self,*args):
        try:
            with socket.socket(socket.AF_UNIX) as s:
                s.settimeout(1);s.connect(self.session.sock_path)
                s.sendall(json.dumps(dict(command=list(args),request_id=31)).encode()+b"\n")
                buf=b""
                while True:
                    data=s.recv(65536)
                    if not data:return None
                    buf+=data
                    while b"\n" in buf:
                        line,buf=buf.split(b"\n",1);doc=json.loads(line)
                        if doc.get("request_id")==31:return doc.get("data",doc.get("error")=="success")
        except (OSError,ValueError):return None

    def test_hover_vertical_slider_scroll_click_and_shared_volume(self):
        state=self.query("get_property","user-data/den/controller")
        self.assertTrue(state["loaded"]);self.assertEqual(state["screen"],"big")
        # vo=null uses the controller's 1280x720 canvas. Hover the bottom-right icon.
        self.query("script-message","den-pointer","1070","692")
        self.assertTrue(wait(lambda:self.query("get_property","user-data/den/controller").get("expanded")))
        self.query("script-message","den-wheel","1")
        self.assertTrue(wait(lambda:self.tv.screens["big"]["volume"]==45))
        self.query("script-message","den-click","press")
        self.assertTrue(wait(lambda:not self.tv.screens["big"]["sound"]))
        self.query("script-message","den-pointer","1080","497")
        self.query("script-message","den-click","down")
        self.query("script-message","den-click","up")
        self.assertTrue(wait(lambda:self.tv.screens["big"]["volume"]==74))
        self.query("quit")
        self.session.thread.join(5)
        self.assertEqual(self.tv.screens["big"]["volume"],74)
        self.assertFalse(os.path.exists(self.session.folder))

    def test_palette_refresh_without_restarting_mpv(self):
        pid=self.session.proc.pid
        first=self.query("get_property","user-data/den/controller")["palette"]["phosphor"]
        with open(self.theme,"w") as f: json.dump(dict(colors={"primary":"#ff7a2a"}),f)
        self.assertTrue(wait(lambda:self.query("get_property","user-data/den/controller")["palette"]["phosphor"]!=first))
        self.assertEqual(self.session.proc.pid,pid)
        self.assertEqual(self.query("get_property","user-data/den/controller")["palette"]["phosphor"],"FF7A2A")


if __name__=="__main__":unittest.main()

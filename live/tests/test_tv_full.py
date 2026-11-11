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


SECRET = "s3cr3t-den-key"


class _Server:
    """A local HTTP server that answers every request with `status`, or (None) takes it and
    never answers: a media server that sends a file's headers to HEAD but never its bytes."""

    def __init__(self, status=None):
        import threading
        self.status, self.held = status, []
        self.sock = socket.socket(); self.sock.bind(("127.0.0.1", 0)); self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try: conn, _ = self.sock.accept()
            except OSError: return
            if self.status is None:
                self.held.append(conn); continue
            try:
                conn.recv(65536)
                conn.sendall(f"HTTP/1.1 {self.status} No\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode())
            except OSError: pass
            conn.close()

    def url(self):
        return f"http://127.0.0.1:{self.port}/Videos/x/stream?static=true&api_key={SECRET}"

    def close(self):
        self.sock.close()
        for c in self.held: c.close()


@unittest.skipUnless(glkit is not None and shutil.which("mpv") and shutil.which("ffmpeg"), "needs PyOpenGL, mpv and ffmpeg")
class DirectFails(unittest.TestCase):
    """A server's file that doesn't play: a transcode at the same moment, and mpv's own error
    in the log (never the address or the key), not a black screen at 00:00."""

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="den-full-test-");self.addCleanup(self.tmp.cleanup)
        self.patch=mock.patch.dict(os.environ,XDG_RUNTIME_DIR=self.tmp.name);self.patch.start();self.addCleanup(self.patch.stop)
        palette=self.tmp.name+"/theme.json"
        with open(palette,"w") as f: json.dump(dict(colors=glkit.T.WICK),f)
        patch=mock.patch.object(glkit.T,"PATH",palette);patch.start();self.addCleanup(patch.stop)
        glkit.T.version(0.)
        self.clip=self.tmp.name+"/transcode.mp4"
        __import__("subprocess").run(["ffmpeg","-v","error","-y","-f","lavfi","-i","color=size=64x64:rate=1",
            "-t","30","-c:v","libx264","-preset","ultrafast",self.clip],check=True)
        self.lines,self.asked=[],[]
        adapter=types.SimpleNamespace(video_stop=lambda s:None)
        def stream(ch,slot,full=False,screen=None,quality=None):
            self.asked.append(quality)
            return dict(url=self.clip,title="Test Card",headers={},start=3,adapter=adapter,quality=quality or "direct")
        self.tv=types.SimpleNamespace(screens={"big":dict(volume=40,sound=True)},motion="full",overrides={},
                                     _tls_ca=lambda:None,feedback=lambda *a:None,log=self.lines.append,
                                     channel=lambda s:(1,{"key":"c"}),slot=lambda ch:object(),stream=stream,
                                     set_sound=lambda *a,**k:None)
        self.adapter=adapter

    def start(self,server,direct=True):
        self.addCleanup(server.close)
        s=dict(url=server.url(),title="Test Card",headers={"Authorization":f'MediaBrowser Token="{SECRET}"'},start=0)
        if direct: s.update(adapter=self.adapter,quality="direct")
        self.session=tvfull.Session(self.tv,"big",s,extra=["--vo=null","--ao=null","--fs=no","--hwdec=no"])
        self.addCleanup(self.close_session)

    def close_session(self):
        self.session.close()
        self.session.proc.wait(timeout=5)
        self.session.thread.join(timeout=5)

    def path(self):
        try:
            with socket.socket(socket.AF_UNIX) as s:
                s.settimeout(1);s.connect(self.session.sock_path)
                s.sendall(json.dumps(dict(command=["get_property","path"],request_id=7)).encode()+b"\n")
                buf=b""
                while True:
                    data=s.recv(65536)
                    if not data:return None
                    buf+=data
                    while b"\n" in buf:
                        line,buf=buf.split(b"\n",1);doc=json.loads(line)
                        if doc.get("request_id")==7:return doc.get("data")
        except (OSError,ValueError):return None

    def assert_no_secret(self):
        for line in self.lines:
            self.assertNotIn(SECRET,line);self.assertNotIn("127.0.0.1",line)

    def test_a_file_that_never_comes_falls_back_to_a_transcode(self):
        with mock.patch.object(tvfull,"DIRECT_OPEN_TIMEOUT",1.5):
            self.start(_Server(None))
            self.assertTrue(wait(lambda:self.path()==self.clip,timeout=12),self.lines)
        self.assertEqual(self.asked,[tvfull.FALLBACK_QUALITY])
        self.assertTrue(any("didn't play (nothing from the server" in l for l in self.lines),self.lines)
        self.assert_no_secret()

    def test_a_refused_file_falls_back_at_once_and_logs_mpvs_error(self):
        self.start(_Server(403))
        self.assertTrue(wait(lambda:self.path()==self.clip,timeout=8),self.lines)
        self.assertTrue(any(l.startswith("tv: full screen mpv:") and "403" in l for l in self.lines),self.lines)
        self.assertTrue(any("a 1080p transcode instead" in l for l in self.lines),self.lines)
        self.assert_no_secret()

    def test_nothing_left_to_try_says_why(self):
        self.start(_Server(403),direct=False)
        self.assertTrue(wait(lambda:any(l.startswith("tv: full screen: can't play Test Card") for l in self.lines),timeout=8),self.lines)
        self.assertEqual(self.asked,[])
        self.assert_no_secret()


if __name__=="__main__":unittest.main()

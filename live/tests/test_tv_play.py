"""The shared search/resolver and CLI; no live socket, real config or real server."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "homelab", "lib"))
import bromigos_tvplay as P
import bromigos_tvremote as R


class Adapter:
    name="library"
    def video_shows(self): return [dict(id="show",title="Space Radio",kind="show",server=self.name)]
    def video_movies(self): return [dict(id="movie",title="Quiet",kind="movie",server=self.name,position=72)]
    def video_show_items(self,id_): return [dict(id=f"ep{n}",title=f"Part {n}",series="Space Radio",season=1,
        episode=n,kind="episode",server=self.name,duration=600) for n in range(1,7)]
    def video_item(self,id_): return self.video_movies()[0] if id_=="movie" else None


class Play(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        env=mock.patch.dict(os.environ,XDG_CONFIG_HOME=self.tmp.name,XDG_STATE_HOME=self.tmp.name,
                            XDG_RUNTIME_DIR=self.tmp.name,BROMIGOS_LIVE_CONFIG=self.tmp.name+"/config.toml")
        env.start();self.addCleanup(env.stop)
        with open(os.environ["BROMIGOS_LIVE_CONFIG"],"w") as f: f.write("[tv]\nenabled=true\n")
        p=mock.patch.object(P,"sources",return_value=[Adapter()]);p.start();self.addCleanup(p.stop)
        p=mock.patch.object(P.TV,"_homelab",return_value=None);p.start();self.addCleanup(p.stop)

    def test_show_season_episode_and_movie_resolution(self):
        self.assertEqual(P.search("Space", "shows")[0]["id"],"show")
        self.assertEqual(P.search("","seasons","show")[0]["season"],1)
        self.assertEqual(len(P.search("","episodes","show",season=1)),6)
        self.assertEqual(P.resolve("Space Radio S01E05")["episode"],5)
        self.assertEqual(P.resolve("Space Radio episode 5")["episode"],5)
        self.assertEqual(P.resolve(id_="movie")["title"],"Quiet")
        with self.assertRaises(P.ChannelError): P.resolve("Missing")
        with self.assertRaises(P.ChannelError): P.resolve(url="http://example.org/secret")

    def test_cli_json_play_and_unavailable_exit(self):
        for answer,code in ((json.dumps(dict(ok=True,message="Playing")),0),(None,3)):
            with mock.patch.object(P,"control",return_value=answer) as ctl, contextlib.redirect_stdout(io.StringIO()) as out:
                result=P.main(["play","--screen","scope","Space Radio S01E05","--resume","--json"])
            self.assertEqual(result,code)
            self.assertEqual(json.loads(out.getvalue())["ok"],code==0)
            payload=json.loads(ctl.call_args.args[0].partition("play-json ")[2])
            self.assertEqual(payload["screen"],"wave"); self.assertTrue(payload["resume"])
            self.assertEqual(payload["item"]["episode"],5)

    def test_downloaded_youtube_metadata_and_private_stream(self):
        from types import SimpleNamespace
        from bromigos_homelab import registry
        adapter = SimpleNamespace(name="downloads", endpoint="https://downloads.example", auth_headers=lambda:{"Authorization":"test-only"},
            sources=lambda:[dict(uuid="feed1")], feed=lambda _:dict(items=[dict(id="clip1", title="Workbench", download="/files/one.mp4")]))
        with mock.patch.object(P.TV, "_homelab", return_value=True), mock.patch.object(registry, "providers", return_value=[adapter]):
            rows = P.search("", "youtube")
            self.assertEqual(rows[0]["download_source"], "feed1")
            self.assertNotIn("download", rows[0]); self.assertNotIn("Authorization", json.dumps(rows))
            stream = P.downloaded_stream(rows[0])
            self.assertEqual(stream["url"], "https://downloads.example/files/one.mp4")
            adapter.feed = lambda _:dict(items=[dict(id="clip1", download="https://elsewhere.example/file")])
            with self.assertRaises(P.ChannelError): P.downloaded_stream(rows[0])

    def test_remote_json_single_screen_uses_the_same_socket(self):
        with mock.patch.object(R,"control",return_value="volume 65") as ctl, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(R.main(["remote","volume-up","--screen","scope","--json"]),0)
        self.assertTrue(json.loads(out.getvalue())["ok"])
        ctl.assert_called_with("tv remote volume-up --screen wave")

    def test_hint_atomic_through_symlink_and_uses_sandbox_config(self):
        sys.path.insert(0,os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),"desktop","lib"))
        target=self.tmp.name+"/tracked.toml"
        with open(target,"w") as f: f.write("# keep\n[tv]\nhover_hint = true # preference\n")
        folder=self.tmp.name+"/bromigos/live";os.makedirs(folder)
        os.symlink(target,folder+"/overrides.toml")
        with mock.patch.object(R,"control",return_value="ok"):
            R.set_hint(False)
        self.assertTrue(os.path.islink(folder+"/overrides.toml"))
        with open(target) as f: text=f.read()
        self.assertIn("hover_hint = false",text);self.assertIn("# keep",text);self.assertIn("# preference",text)


if __name__ == "__main__": unittest.main()

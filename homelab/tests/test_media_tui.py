"""`bromigos media`, the media library's terminal UI (mediatui.py), driven by Textual's pilot
against the fake media stack (mediafake.py: made-up titles), and the CLI's library verbs.

    PYTHONPATH=lib python -m unittest tests.test_media_tui
    MEDIA_SCREENSHOTS=DIR …          also write each tab as an SVG (the docs' pictures)

Skipped without Textual (python-textual).
"""
import asyncio
import contextlib
import io
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

os.environ.setdefault("BROMIGOS_HOMELAB_CONFIG", "/nonexistent")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mediafake as F                                          # noqa: E402
from bromigos_homelab import config, registry                  # noqa: E402
from bromigos_homelab import mediareq as M                     # noqa: E402

try:
    import textual  # noqa: F401  (skips the TUI tests without it)
    from bromigos_homelab import mediatui as T
except ImportError:
    T = None


class Stack(unittest.TestCase):
    def setUp(self):
        self.srv = F.Server()
        self.st = self.srv.state
        self.tmp = tempfile.mkdtemp(prefix="media-tui-")
        toml = F.homelab_toml(os.path.join(self.tmp, "homelab.toml"), self.srv.url, None,
                              '[media]\naudio = ["en", "ja"]\nsubtitles = ["en"]\n')
        self.channel_config = os.path.join(self.tmp, "live-config.toml")
        with open(self.channel_config, "w") as f: f.write("# sandbox den channels\n[tv]\nenabled = true\n")
        self.patches = [mock.patch.dict(os.environ, {"BROMIGOS_LIVE_CONFIG": self.channel_config,
                                                   "XDG_STATE_HOME": self.tmp}),
                        mock.patch.object(config, "USER", toml),
                        mock.patch.object(M, "STATE_FILE", os.path.join(self.tmp, "state.json")),
                        mock.patch.object(M, "_wait", lambda fn, timeout=60, every=2.0: fn())]
        if T is not None:
            self.patches += [mock.patch.object(T.CH, "control", return_value=None),
                             mock.patch.object(T.CH.TV, "state", return_value={}),
                             mock.patch.object(T.CH.TV, "cached_items", return_value=None),
                             mock.patch.object(T.CH.TV, "fetch_items", return_value={"items": []})]
        for p in self.patches:
            p.start()
        config._cache["sig"] = None
        registry._inst["sig"] = None
        self.sh = self.st.add_series(8001, [1], profile=11, files=6, series_type="anime")
        self.pm = self.st.add_series(8004, [1, 2, 3], profile=8, files=4)
        self.st.movies[250] = dict(F.radarr_lookup(7002), id=250, qualityProfileId=11, monitored=True, hasFile=True,
                                   minimumAvailability="released", sizeOnDisk=24 * 10 ** 9, added="2026-10-03T00:00:00Z",
                                   movieFile={"id": 9, "size": 24 * 10 ** 9, "quality": {"quality": {"name": "Remux-1080p"}},
                                              "mediaInfo": {"audioLanguages": "eng/jpn"}})
        self.st.movies[251] = dict(F.radarr_lookup(7001), id=251, qualityProfileId=8, monitored=True, hasFile=False,
                                   minimumAvailability="released", added="2026-10-04T00:00:00Z")
        F.seed_music(self.st)
        self.st.seerr_media = [{"id": 77, "mediaType": "tv", "tmdbId": 8001, "tvdbId": 90001}]
        self.st.calendar["sonarr"] = [{"airDateUtc": "2026-11-02T02:00:00Z", "seasonNumber": 4, "episodeNumber": 1,
                                       "title": "Reopening", "hasFile": False, "series": {"title": "Paper Moon Cafe"}}]

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.srv.close()
        config._cache["sig"] = None
        registry._inst["sig"] = None

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(sys.stdin, "isatty", lambda: False):
            code = M.main(list(argv))
        return code, out.getvalue(), err.getvalue()


class Library(Stack):
    def test_library_records(self):
        lab = M.Lab()
        tv = {r["title"]: r for r in M.library(lab, "tv")}
        sh = tv["Starlight Harbor"]
        self.assertEqual((sh["files"], sh["size"], sh["profile"], sh["new_items"]),
                         (6, 12 * 10 ** 9, "Remux-1080p - Anime (English audio)", True))
        self.assertEqual(sh["missing"], 20)
        mv = {r["title"]: r for r in M.library(lab, "movies")}
        self.assertEqual((mv["Lanterns of Kiri"]["quality"], mv["Lanterns of Kiri"]["audio"]), ("Remux-1080p", ["en", "ja"]))
        self.assertEqual(mv["Comet Drift"]["release"], "in cinemas 2027-03-12, digital TBA")
        al = M.albums(lab, 300)
        self.assertEqual([(a["title"], a["format"], a["tracks"]) for a in al], [("Glass Valley", "FLAC", 10),
                                                                               ("Low Tide", "-", 0)])
        t = M.totals(lab)
        self.assertEqual((t["tv"]["count"], t["movies"]["count"], t["music"]["count"], t["free"]), (2, 2, 1, 22 * 10 ** 12))

    def test_cli_delete_needs_the_name_or_yes(self):
        code, out, err = self.cli("delete", "Starlight Harbor")
        self.assertEqual(code, 2)
        self.assertIn("Delete Starlight Harbor: 1 season, 6 files, files and all? It frees 12 GB.", out)
        self.assertEqual(self.st.deleted, [])
        with mock.patch.object(sys.stdin, "isatty", lambda: True), mock.patch("builtins.input", lambda q="": "starlight"):
            code = M.main(["delete", "Starlight Harbor"])
        self.assertEqual((code, self.st.deleted), (1, []))                      # the wrong name: nothing goes
        with mock.patch.object(sys.stdin, "isatty", lambda: True), \
                mock.patch("builtins.input", lambda q="": "starlight harbor"), contextlib.redirect_stdout(io.StringIO()):
            code = M.main(["delete", "Starlight Harbor", "--exclude"])
        self.assertEqual(code, 0)
        self.assertEqual(self.st.deleted, [("sonarr", self.sh, ["true"], ["true"])])
        self.assertEqual(self.st.seerr_media, [])                               # its Seerr entry is gone too
        self.assertEqual(sorted(self.st.rescans), ["jellyfin", "plex"])

    def test_cli_delete_a_season_keeps_the_show(self):
        code, out, err = self.cli("delete", "Paper Moon Cafe", "--season", "1", "--yes")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.st.deleted_files), 4)
        self.assertIn(self.pm, self.st.series)
        self.assertFalse(next(z for z in self.st.series[self.pm]["seasons"] if z["seasonNumber"] == 1)["monitored"])

    def test_cli_monitor_profile_refresh(self):
        self.cli("monitor", "Paper Moon Cafe", "--new", "--off")
        self.assertEqual(self.st.series[self.pm]["monitorNewItems"], "none")
        self.cli("monitor", "Paper Moon Cafe", "--season", "2", "--off")
        self.assertFalse(self.st.series[self.pm]["seasons"][1]["monitored"])
        code, out, _ = self.cli("profile", "Paper Moon Cafe", "WEB-1080p")
        self.assertEqual(self.st.series[self.pm]["qualityProfileId"], 7)
        self.cli("refresh", "Comet Drift")
        self.assertIn(("radarr", {"name": "MoviesSearch", "movieIds": [251]}), self.st.commands)


@unittest.skipIf(T is None, "python-textual isn't installed: the media TUI isn't built")
class TUI(Stack):
    def run_app(self, fn, start="tv", size=(140, 40)):
        async def go():
            app = T.MediaApp(T.Live(M.Lab()), start=start)
            app.src.open = lambda url: self.opened.append(url)
            async with app.run_test(size=size) as pilot:
                await self.settle(app, pilot)
                await fn(app, pilot)
            self.assertFalse(app.is_running)
        self.opened = []
        asyncio.run(go())

    async def settle(self, app, pilot, n=12):
        for _ in range(n):
            await pilot.pause(0.05)
        await app.workers.wait_for_complete()
        await pilot.pause(0.05)

    def shot(self, app, name):
        d = os.environ.get("MEDIA_SCREENSHOTS")
        if d:
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, f"media-{name}.svg"), "w") as f:
                f.write(app.export_screenshot(title=f"bromigos media · {name}"))

    def test_quit_and_text_shortcuts(self):
        for tid in T.MediaApp.TABS:
            async def fn(app, pilot):
                if tid in app.shown:
                    app.action_filter()
                elif tid == "search":
                    app.query_one("#search-q").focus()
                if isinstance(app.focused, T.Input):
                    field = app.focused
                    await pilot.press("q", "H", "L", "left_square_bracket", "right_square_bracket")
                    self.assertEqual(field.value, "qHL[]")
                    self.assertFalse(app._exit)
                    self.assertEqual(app.query_one("#tabs").active, tid)
                await pilot.press("ctrl+c")
                self.assertTrue(app._exit)
                self.assertEqual(self.st.deleted, [])
            self.run_app(fn, start=tid)
        async def quit_list(app, pilot):
            app.query_one("#tv-list").focus()
            await pilot.press("q")
            self.assertTrue(app._exit)
        self.run_app(quit_list)

    def test_interrupt_cancels_modals_without_quitting(self):
        for dialog in ("delete", "profile", "request"):
            async def fn(app, pilot):
                if dialog == "delete":
                    app.action_delete()
                elif dialog == "profile":
                    app.action_profile()
                else:
                    app.push_screen(T.Request(app.src, {"kind": "tv", "title": "Test show"}))
                await pilot.pause()
                await pilot.press("ctrl+c")
                self.assertNotIsInstance(app.screen, T.ModalScreen)
                self.assertFalse(app._exit)
                self.assertEqual(self.st.deleted, [])
                self.assertEqual(self.st.deleted_files, [])
            self.run_app(fn)

    def test_play_picker_drills_into_seasons_and_episodes(self):
        from bromigos_homelab import tvplayui as U
        show = dict(id="show", title="Starlight Harbor", kind="show", server="library")
        season = dict(id="show", title="Season 1", kind="season", season=1, server="library")
        episode = dict(id="ep5", title="Episode 5", series="Starlight Harbor", kind="episode", server="library")
        def search(query="", **scope):
            return {"shows": [show], "seasons": [season], "episodes": [episode],
                    "movies": [dict(id="movie", title="Lanterns of Kiri", kind="movie", server="library")]}[scope["kind"]]
        async def fn(app, pilot):
            await pilot.press("p")
            await self.settle(app, pilot)
            self.assertIsInstance(app.screen, U.PlayOnDen)
            await pilot.press("enter")
            await self.settle(app, pilot)
            self.assertEqual(app.screen.rows[0]["kind"], "season")
            await pilot.press("enter")
            await self.settle(app, pilot)
            self.assertEqual(app.screen.rows[0]["id"], "ep5")
            await pilot.press("enter")
            await self.settle(app, pilot)
            self.assertEqual(play.call_args.kwargs["item"]["id"], "ep5")
            self.assertEqual(play.call_args.kwargs["screen"], "big")
            app.action_tab("movies")
            await self.settle(app, pilot)
            await pilot.press("p")
            await self.settle(app, pilot)
            self.assertEqual(app.screen.rows[0]["kind"], "movie")
            await pilot.press("ctrl+c")
            self.assertFalse(app._exit)
            self.assertNotIsInstance(app.screen, U.PlayOnDen)
        with mock.patch.object(U.TVP, "search", side_effect=search), mock.patch.object(U.TVP, "play", return_value={"message": "Playing"}) as play:
            self.run_app(fn)

    def test_den_picker_late_results_keep_search_focus(self):
        from bromigos_homelab import tvplayui as U
        started, finish = threading.Event(), threading.Event()
        def search(query="", **scope):
            started.set()
            finish.wait(5)
            return [{"id": "movie", "title": "Lanterns of Kiri", "kind": "movie", "server": "library"}]
        async def fn(app, pilot):
            app.push_screen(U.PlayOnDen())
            await pilot.pause()
            self.assertTrue(started.is_set())
            field = app.screen.query_one("#den-search")
            field.focus()
            await pilot.press("q", "H", "L")
            finish.set()
            await self.settle(app, pilot, 3)
            self.assertIs(app.focused, field)
            self.assertEqual(field.value, "qHL")
            await pilot.press("enter")
            await self.settle(app, pilot, 3)
            self.assertEqual(app.focused.id, "den-results")
        try:
            with mock.patch.object(U.TVP, "search", side_effect=search):
                self.run_app(fn)
        finally:
            finish.set()

    def test_modal_blocks_background_shortcuts(self):
        async def fn(app, pilot):
            await pilot.press("D")
            await pilot.pause()
            app.screen.query_one("#del-yes").focus()
            await pilot.press("right_square_bracket")
            await pilot.pause()
            await pilot.press("q", "L", "8", "r", "c")
            self.assertIsInstance(app.screen, T.Confirm)
            self.assertEqual(app.query_one("#tabs").active, "tv")
            self.assertFalse(app._exit)
            await pilot.press("escape")
            self.assertNotIsInstance(app.screen, T.Confirm)
            self.assertEqual(self.st.deleted, [])
        self.run_app(fn)

    def test_tabs_to_content_and_back_on_every_tab(self):
        async def fn(app, pilot):
            for tid in app.TABS:
                for down, up in (("down", "up"), ("j", "k")):
                    with self.subTest(tab=tid, down=down):
                        app.action_tab(tid)
                        await pilot.pause()
                        bar = app.query_one("#tabs Tabs", T.Tabs)
                        bar.focus()
                        await pilot.press(down)
                        self.assertIsInstance(app.focused, T.MediaTable)
                        table = app.focused
                        table.move_cursor(row=0)
                        await pilot.press(up)
                        self.assertIs(app.focused, bar)
                        self.assertEqual(app.query_one("#tabs").active, tid)
        self.run_app(fn)

    def test_tab_bar_vim_keys_match_arrows_and_keep_focus(self):
        async def fn(app, pilot):
            bar = app.query_one("#tabs Tabs", T.Tabs)
            for tid in app.TABS:
                for right, left in (("right", "left"), ("l", "h")):
                    with self.subTest(tab=tid, right=right):
                        app.action_tab(tid)
                        await pilot.pause()
                        bar.focus()
                        await pilot.press(right)
                        self.assertEqual(app.query_one("#tabs").active,
                                         app.TABS[(app.TABS.index(tid) + 1) % len(app.TABS)])
                        self.assertIs(app.focused, bar)
                        await pilot.press(left)
                        self.assertEqual(app.query_one("#tabs").active, tid)
                        self.assertIs(app.focused, bar)
            app.action_tab("search")
            await pilot.pause()
            await pilot.press("h", "l")
            self.assertEqual(app.query_one("#search-q").value, "hl")
            self.assertEqual(app.query_one("#tabs").active, "search")
        self.run_app(fn)

    def test_table_motion_panes_and_global_tabs(self):
        async def fn(app, pilot):
            table = app.query_one("#tv-list")
            table.focus()
            await pilot.press("g", "j")
            self.assertEqual(table.cursor_row, 1)
            await pilot.press("k")
            self.assertEqual(table.cursor_row, 0)
            await pilot.press("G")
            self.assertEqual(table.cursor_row, table.row_count - 1)
            await pilot.press("g", "ctrl+d", "ctrl+u")
            self.assertIs(app.focused, table)
            for right, left in (("right", "left"), ("l", "h")):
                await pilot.press(right)
                self.assertIs(app.focused, app.query_one("#tv-sub"))
                await pilot.press(left)
                self.assertIs(app.focused, table)
            await pilot.press("slash")
            await pilot.pause()
            await pilot.press("right_square_bracket")
            self.assertEqual(app.query_one("#tv-filter").value, "]")
            await pilot.press("escape", "right_square_bracket")
            await pilot.pause()
            self.assertEqual(app.query_one("#tabs").active, "movies")
            await pilot.press("H")
            await pilot.pause()
            self.assertEqual(app.query_one("#tabs").active, "tv")
            await pilot.press("L")
            await pilot.pause()
            await pilot.press("left_square_bracket")
            await pilot.pause()
            self.assertEqual(app.query_one("#tabs").active, "tv")
        self.run_app(fn)

    def test_media_wrapper_opens_channels_tab(self):
        import runpy
        program=os.path.join(os.path.dirname(os.path.dirname(__file__)),'bin','bromigos-media')
        wrapper=runpy.run_path(program,run_name='test_wrapper')
        with mock.patch.object(T,'main',return_value=0) as main:
            self.assertEqual(wrapper['main'](['channels']),0)
            main.assert_called_once_with(['channels'])

    def seed_channels(self):
        with open(self.channel_config, 'a') as f:
            f.write('\n# A picked block\n[[tv.channel]]\nname = "Night Block" # name kept\n'
                    'shows = ["One", "Two"] # order kept\norder = "in-order"\nbumpers = true\n')

    def test_tv_add_and_remove_channel_pick_and_marker(self):
        self.seed_channels()
        async def fn(app, pilot):
            title = app.query_one('#tv-list').get_row_at(0)[1]
            await pilot.press('c');await pilot.pause()
            app.screen.query_one('#channel-pick').value = 'add:1'
            await pilot.click('#channel-use');await self.settle(app,pilot,4)
            self.assertIn(title,app.channel_store.load().channels()[0]['shows'])
            self.assertIn('◇',app.query_one('#tv-list').get_row_at(0)[0])
            await pilot.press('c');await pilot.pause()
            app.screen.query_one('#channel-pick').value = 'remove:1'
            await pilot.click('#channel-use');await self.settle(app,pilot,4)
            self.assertNotIn(title,app.channel_store.load().channels()[0]['shows'])
            self.assertNotIn('◇',app.query_one('#tv-list').get_row_at(0)[0])
            self.assertIn('# name kept',app.channel_store.load().text)
            self.assertIn('# order kept',app.channel_store.load().text)
        self.run_app(fn)

    def test_create_channel_from_tv_picker(self):
        async def fn(app,pilot):
            title = app.query_one('#tv-list').get_row_at(0)[1]
            await pilot.press('c');await pilot.pause()
            await pilot.click('#channel-use');await pilot.pause()
            app.screen.query_one('#channel-name').value = 'New Block'
            await pilot.click('#channel-save');await self.settle(app,pilot,4)
            row=app.channel_store.load().channels()[0]
            self.assertEqual((row['name'],row['shows']),('New Block',[title]))
        self.run_app(fn)

    def test_static_hosts_the_channels_tab(self):
        """STATIC on CHANNELS: big and fiddling with the antenna while there are none, then his
        head beside the selected channel (not on a screen: standing by)."""
        if T.STATIC is None:
            self.skipTest("no bromigos_static_term")
        async def empty(app, pilot):
            await pilot.press('8'); await self.settle(app, pilot, 3)
            fig = app.query_one('#ch-figure')
            self.assertTrue(fig.display); self.assertEqual(fig.pose, 'antenna')
            self.assertFalse(app.query_one('#ch-host').display)
        self.run_app(empty)
        self.seed_channels()
        async def one(app, pilot):
            await pilot.press('8'); await self.settle(app, pilot, 3)
            self.assertFalse(app.query_one('#ch-figure').display)
            self.assertTrue(app.query_one('#ch-host').display)
            self.assertEqual(app.query_one('#ch-static').face, 'neutral')
            self.assertIn("Not on a screen", str(app.query_one('#ch-host-text').render()))
        self.run_app(one)

    def test_channel_reorder_delete_undo_and_comments(self):
        self.seed_channels()
        async def fn(app,pilot):
            await pilot.press('8');await pilot.pause()
            await pilot.press('l');await pilot.pause()
            app.query_one('#ch-items').move_cursor(row=1)
            await pilot.press('alt+up');await self.settle(app,pilot,3)
            self.assertEqual(app.channel_store.load().channels()[0]['shows'],['Two','One'])
            self.assertEqual(app.query_one('#ch-items').cursor_row,0)
            await pilot.press('h','v','b');await self.settle(app,pilot,3)
            row=app.channel_store.load().channels()[0]
            self.assertEqual(row['order'],'alternate');self.assertFalse(row['bumpers'])
            self.shot(app, 'channels')
            await pilot.press('D');await pilot.pause()
            await pilot.press('escape');self.assertEqual(len(app.channel_store.load().channels()),1)
            await pilot.press('D');await pilot.pause()
            await pilot.click('#del-yes');await self.settle(app,pilot,3)
            self.assertEqual(app.channel_store.load().channels(),[])
            await pilot.press('ctrl+z');await self.settle(app,pilot,3)
            self.assertEqual(app.channel_store.load().channels()[0]['name'],'Night Block')
            self.assertIn('# order kept',app.channel_store.load().text)
            self.assertEqual(self.st.deleted,[])
        self.run_app(fn)

    def test_channel_poll_reads_live_state_without_fetching_content(self):
        self.seed_channels()
        async def fn(app,pilot):
            with mock.patch.object(T.CH.TV,'fetch_items') as fetch, mock.patch.object(T.CH,'live_state',
                return_value={'screens':{'big':{'key':'night-block','now':'Broadcast','next':'After'}}}):
                app.poll_channels();await self.settle(app,pilot,3)
                fetch.assert_not_called()
                self.assertEqual(app.channel_rows[0]['on_screens'],['big'])
                self.assertEqual(app.channel_rows[0]['now'],'Broadcast')
        self.run_app(fn)

    def test_channel_picker_from_movies_music_youtube_upcoming_and_search(self):
        self.seed_channels()
        async def fn(app,pilot):
            url='https://www.youtube.com/playlist?list=test'
            app.show_youtube([{'name':'Clips','url':url}])
            app.show_found([{'kind':'movie','title':'Comet Drift'}],focus=False)
            for tab, value in (('movies',None),('music',None),('youtube',url),('upcoming','Paper Moon Cafe'),
                               ('search','Comet Drift')):
                app.action_tab(tab);await pilot.pause()
                if tab=='search': app.query_one('#search-list').focus()
                await pilot.click('#title-channel');await pilot.pause()
                self.assertIsInstance(app.screen,T.ChannelPicker,tab)
                title=app.screen.title_
                if value:self.assertEqual(title,value)
                picker = app.screen.query_one('#channel-pick')
                if T.CH.membership(title, [app.channel_rows[0]]):
                    # Search can find the same film already added from Movies.
                    picker.value = 'remove:1'
                    await pilot.press('escape');await pilot.pause()
                else:
                    picker.value = 'add:1'
                    await pilot.click('#channel-use');await self.settle(app,pilot,2)
                rows=app.channel_store.load().channels()[0]
                self.assertIn(title,rows['items'] if tab in ('movies','music','youtube','search') else rows['shows'])
        self.run_app(fn)

    def test_channel_button_keeps_the_selected_album_and_keyboard_activation(self):
        self.seed_channels()
        async def fn(app, pilot):
            app.action_tab("music")
            await self.settle(app, pilot, 2)
            table = app.query_one("#music-sub")
            table.focus()
            await pilot.pause()
            album = app.subrows["music"][table.cursor_row]["title"]
            artist = app.current("music")[1]["title"]
            app.channel_store.item("Night Block", "music:album:" + album, item_kind="music")
            app.channel_store.create(name="Artists", items=["music:artist:" + artist])
            app.load_channels()
            await self.settle(app, pilot, 3)
            table.focus()
            await pilot.pause()
            self.assertIn("Night Block", str(app.query_one("#title-membership").render()))
            app.query_one("#music-list").focus()
            await pilot.pause()
            self.assertIn("Artists", str(app.query_one("#title-membership").render()))
            self.assertNotIn("Night Block", str(app.query_one("#title-membership").render()))
            table.focus()
            await pilot.pause()
            await pilot.click("#title-channel")
            await pilot.pause()
            self.assertEqual(app.screen.title_, "music:album:" + album)
            await pilot.press("escape")
            await pilot.pause()
            app.query_one("#title-channel").focus()
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app.screen.title_, "music:album:" + album)
            await pilot.press("escape")
            app.action_tab("channels")
            await pilot.pause()
            self.assertFalse(app.query_one("#title-actions").display)
        self.run_app(fn)

    def test_add_to_channel_with_keyboard_only(self):
        self.seed_channels()
        async def fn(app, pilot):
            title = app.query_one("#tv-list").get_row_at(0)[1]
            await pilot.press("c")
            await pilot.pause()
            await pilot.press("enter", "down", "enter")
            self.shot(app, "channel-picker")
            await pilot.press("tab", "right", "enter")
            await self.settle(app, pilot, 3)
            self.assertIn(title, app.channel_store.load().channels()[0]["shows"])
        self.run_app(fn)

    def test_selected_and_hovered_title_names_its_channels_and_refreshes_after_removal(self):
        self.seed_channels()
        async def fn(app, pilot):
            table = app.query_one("#tv-list")
            title = table.get_row_at(0)[1]
            app.channel_store.item("Night Block", title)
            app.channel_store.create(name="Weekend", shows=[title])
            app.load_channels()
            await self.settle(app, pilot, 3)
            table.focus()
            await pilot.pause()
            membership = str(app.query_one("#title-membership").render())
            self.assertIn("Night Block", membership)
            self.assertIn("Weekend", membership)
            await pilot.hover("#tv-list", offset=(10, 2))
            await pilot.pause()
            self.assertIn("Night Block", table.tooltip)
            self.assertIn("Weekend", table.tooltip)
            self.shot(app, "channel-membership")
            await pilot.press("c")
            await pilot.pause()
            self.assertIn("Night Block", str(app.screen.query_one("#channel-membership").render()))
            selector = app.screen.query_one("#channel-pick")
            options = dict((value, str(label)) for label, value in selector._options)
            self.assertIn("Already in Night Block", options["remove:1"])
            self.assertNotIn("add:1", options)
            selector.value = "remove:1"
            await pilot.click("#channel-use")
            await self.settle(app, pilot, 3)
            membership = str(app.query_one("#title-membership").render())
            self.assertNotIn("Night Block", membership)
            self.assertIn("Weekend", membership)
            self.assertIn("Channels: Weekend", table.hints[0])
        self.run_app(fn)

    def test_create_and_reorder_channels(self):
        self.seed_channels()
        async def fn(app,pilot):
            await pilot.press('8','ctrl+n');await pilot.pause()
            app.screen.query_one('#channel-name').value='Films'
            app.screen.query_one('#channel-kind').value='library'
            app.screen.query_one('#channel-source').value='Movies'
            await pilot.click('#channel-save');await self.settle(app,pilot,3)
            app.query_one('#ch-list').move_cursor(row=1)
            await pilot.press('alt+up');await self.settle(app,pilot,3)
            self.assertEqual(app.channel_store.load().channels()[0]['name'],'Films')
            self.assertEqual(app.selected_channel()['name'],'Films')
        self.run_app(fn)

    def test_every_tab_shows_its_data(self):
        async def fn(app, pilot):
            top = str(app.query_one("#top").render())
            self.assertIn("2 shows", top)
            self.assertIn("22 TB free", top)
            tv = app.query_one("#tv-list")
            titles = {tv.get_row_at(i)[1] for i in range(tv.row_count)}
            self.assertEqual(titles, {"Starlight Harbor", "Paper Moon Cafe"})
            self.assertIn("Profile", str(app.query_one("#tv-detail").render()))
            self.assertGreater(app.query_one("#tv-sub").row_count, 0)            # its seasons
            self.shot(app, "tv")
            for key, tid, table in (("2", "movies", "#movies-list"), ("3", "music", "#music-list"),
                                    ("6", "upcoming", "#up-list")):
                await pilot.press(key)
                await self.settle(app, pilot, 4)
                self.assertEqual(app.query_one("#tabs").active, tid)
                self.assertGreater(app.query_one(table).row_count, 0, tid)
                self.shot(app, tid)
            await pilot.press("3", "l")                                         # the artist's albums
            await self.settle(app, pilot, 4)
            self.assertEqual(app.query_one("#music-sub").get_row_at(0)[3], "FLAC")
            await pilot.press("5")
            await self.settle(app, pilot, 4)
            self.shot(app, "downloads")
        self.run_app(fn)

    def test_delete_dialog_arrows_enter_and_exclusion_without_mouse(self):
        async def fn(app, pilot):
            await pilot.press("D")
            await self.settle(app, pilot, 2)
            self.assertIs(app.focused, app.screen.query_one("#del-no"))
            await pilot.press("right")
            self.assertIs(app.focused, app.screen.query_one("#del-yes"))
            await pilot.press("left", "enter")
            await self.settle(app, pilot, 2)
            self.assertNotIsInstance(app.screen, T.Confirm)
            self.assertEqual(self.st.deleted, [])
            await pilot.press("D")
            await self.settle(app, pilot, 2)
            await pilot.press("up")
            checkbox = app.screen.query_one("#del-exclude")
            self.assertIs(app.focused, checkbox)
            await pilot.press("enter")
            self.assertTrue(checkbox.value)
            await pilot.press("down", "right")
            self.assertIs(app.focused, app.screen.query_one("#del-yes"))
            await pilot.press("enter")
            await self.settle(app, pilot, 4)
            self.assertTrue(self.st.deleted)
        self.run_app(fn)

    def test_delete_cancel_then_confirm_with_button(self):
        async def fn(app, pilot):
            tv = app.query_one("#tv-list")
            row = next(i for i in range(tv.row_count) if tv.get_row_at(i)[1] == "Starlight Harbor")
            tv.move_cursor(row=row)
            await self.settle(app, pilot, 2)
            await pilot.press("D")
            await self.settle(app, pilot, 2)
            self.assertIn("Delete Starlight Harbor: 1 season, 6 files, files and all?",
                          str(app.screen.query_one("#del-what").render()))
            self.assertFalse(app.screen.query_one("#del-yes").disabled)
            self.assertIs(app.focused, app.screen.query_one("#del-no"))
            self.assertFalse(app.screen.query("#del-name"))
            self.shot(app, "delete")
            await pilot.press("enter")
            await self.settle(app, pilot, 2)
            self.assertEqual(self.st.deleted, [])                               # default Cancel: nothing went
            await pilot.press("D")
            await self.settle(app, pilot, 2)
            await pilot.click("#del-yes")
            await self.settle(app, pilot, 6)
            self.assertEqual(self.st.deleted, [("sonarr", self.sh, ["true"], ["false"])])
            self.assertNotIn(self.sh, self.st.series)
        self.run_app(fn)

    def test_delete_a_season_with_confirmation_button(self):
        async def fn(app, pilot):
            tv = app.query_one("#tv-list")
            tv.move_cursor(row=next(i for i in range(tv.row_count) if tv.get_row_at(i)[1] == "Paper Moon Cafe"))
            await self.settle(app, pilot, 3)
            sub = app.query_one("#tv-sub")
            sub.focus()
            await self.settle(app, pilot, 2)
            sub.move_cursor(row=0)                                             # Season 1 (no specials here)
            await self.settle(app, pilot, 1)
            await pilot.press("D")
            await self.settle(app, pilot, 2)
            self.assertIn("Paper Moon Cafe season 1: 4 episode files", str(app.screen.query_one("#del-what").render()))
            app.screen.query_one("#del-no").focus()
            await pilot.click("#del-yes")
            await self.settle(app, pilot, 6)
            self.assertEqual(len(self.st.deleted_files), 4)
            self.assertIn(self.pm, self.st.series)
        self.run_app(fn)

    def test_monitor_profile_open_and_search_now(self):
        async def fn(app, pilot):
            tv = app.query_one("#tv-list")
            tv.move_cursor(row=next(i for i in range(tv.row_count) if tv.get_row_at(i)[1] == "Paper Moon Cafe"))
            await self.settle(app, pilot, 2)
            await pilot.press("n")
            await self.settle(app, pilot, 3)
            self.assertEqual(self.st.series[self.pm]["monitorNewItems"], "none")
            await pilot.press("f")
            await self.settle(app, pilot, 2)
            self.assertIn(("sonarr", {"name": "SeriesSearch", "seriesId": self.pm}), self.st.commands)
            await pilot.press("O")
            await self.settle(app, pilot, 2)
            self.assertEqual(self.opened, [f"{self.srv.url}/seerr/tv/8004"])
            await pilot.press("P")
            await self.settle(app, pilot, 2)
            app.screen.query_one("#prof").value = 7
            await pilot.click("#prof-yes")
            await self.settle(app, pilot, 3)
            self.assertEqual(self.st.series[self.pm]["qualityProfileId"], 7)
        self.run_app(fn)

    def test_search_tab_button_finds_a_title_outside_the_library(self):
        self.st.movies.pop(251)
        async def fn(app, pilot):
            await pilot.press("ctrl+f")
            await self.settle(app, pilot, 2)
            self.assertEqual(app.query_one("#tabs").active, "search")
            self.assertIs(app.focused, app.query_one("#search-q"))
            await pilot.click("#search-go")
            self.assertEqual(app.found, [])
            self.assertIs(app.focused, app.query_one("#search-q"))
            app.query_one("#search-q").value = "comet"
            app.query_one("#search-kind").value = "movie"
            await pilot.click("#search-go")
            await self.settle(app, pilot, 6)
            table = app.query_one("#search-list")
            self.assertEqual(table.get_row_at(0)[1], "Comet Drift")
            self.assertEqual(table.get_row_at(0)[-1], "-")
            self.assertEqual(self.st.seerr_requests, [])
            self.assertEqual(self.st.commands, [])
            self.shot(app, "search")
            await pilot.press("enter")
            await self.settle(app, pilot, 2)
            self.assertIsInstance(app.screen, T.Request)
        self.run_app(fn, size=(100, 35))

    def test_search_tab_command_preserves_cli_search_with_a_title(self):
        import runpy
        entry = runpy.run_path(os.path.join(os.path.dirname(__file__), "../bin/bromigos-media"))
        with mock.patch.object(T, "main", return_value=0) as tui, \
                mock.patch.object(M, "main", return_value=0) as cli:
            self.assertEqual(entry["main"](["search"]), 0)
            tui.assert_called_once_with(["search"])
            self.assertEqual(entry["main"](["search", "Comet Drift"]), 0)
            cli.assert_called_once_with(["search", "Comet Drift"])

    def test_request_preview_tracks_options_before_submission(self):
        async def fn(app, pilot):
            item = app.src.search("comet", "movie")[0]
            request = T.Request(app.src, item)
            app.push_screen(request)
            await self.settle(app, pilot, 3)
            self.assertIsNotNone(request.plan)
            self.assertFalse(request.query_one("#req-yes").disabled)
            self.assertEqual(self.st.commands, [])
            old_plan = request.plan
            request.query_one("#req-audio").value = "ja"
            request.show_plan()
            self.assertIsNone(request.plan)
            self.assertTrue(request.query_one("#req-yes").disabled)
            await self.settle(app, pilot, 3)
            self.assertIsNot(request.plan, old_plan)
            self.assertEqual(request._plan_opts["audio"], "ja")
            with mock.patch.object(app.src, "request", return_value={"message": "Requested"}) as submit:
                request.query_one("#req-yes").focus()
                approved = request.plan
                await pilot.press("enter")
                await self.settle(app, pilot, 3)
                submit.assert_called_once_with(approved)
            self.assertNotIsInstance(app.screen, T.Request)
        self.run_app(fn)

    def test_help_and_channel_forms_keyboard_only_at_small_size(self):
        async def fn(app, pilot):
            await pilot.press("question_mark")
            await pilot.pause()
            self.assertIsInstance(app.screen, T.Dialog)
            self.shot(app, "help")
            await pilot.press("escape")
            app.push_screen(T.ChannelForm(value="", create=False))
            await pilot.pause()
            field = app.screen.query_one("#channel-name")
            field.focus()
            await pilot.press(*"qHL test")
            self.assertEqual(field.value, "qHL test")
            await pilot.press("tab")
            self.assertEqual(app.focused.id, "channel-cancel")
            await pilot.press("right")
            self.assertEqual(app.focused.id, "channel-save")
            self.shot(app, "channel-form")
            await pilot.press("ctrl+c")
            self.assertFalse(app._exit)
            self.assertNotIsInstance(app.screen, T.ChannelForm)
        self.run_app(fn, size=(80, 24))

    def test_request_actions_fit_narrow_terminals(self):
        for size in ((60, 18), (40, 12)):
            async def fn(app, pilot):
                app.push_screen(T.Request(app.src, app.src.search("comet", "movie")[0]))
                await self.settle(app, pilot, 3)
                for button in app.screen.query(T.Button):
                    self.assertGreater(button.region.width, 0)
                    self.assertLessEqual(button.region.right, app.screen.region.right)
                self.shot(app, "request-" + str(size[0]))
                await pilot.press("ctrl+c")
                self.assertFalse(app._exit)
            self.run_app(fn, size=size)

    def test_confirmed_request_cannot_cancel_while_committing(self):
        started, finish = threading.Event(), threading.Event()
        def submit(plan):
            started.set()
            finish.wait(5)
            return {"message": "Requested"}
        async def fn(app, pilot):
            request = T.Request(app.src, app.src.search("comet", "movie")[0])
            app.push_screen(request)
            await self.settle(app, pilot, 3)
            with mock.patch.object(app.src, "request", side_effect=submit):
                request.query_one("#req-yes").focus()
                await pilot.press("enter")
                await pilot.pause()
                self.assertTrue(started.is_set())
                self.assertTrue(request._submitting)
                await pilot.press("escape", "ctrl+c", "q")
                self.assertIs(app.screen, request)
                self.assertTrue(request.query_one("#req-no").disabled)
                finish.set()
                await self.settle(app, pilot, 3)
            self.assertNotIsInstance(app.screen, T.Request)
            self.assertFalse(app._exit)
        try:
            self.run_app(fn)
        finally:
            finish.set()

    def test_delete_confirmation_buttons_fit_small_terminal(self):
        async def fn(app, pilot):
            app.action_delete()
            await pilot.pause()
            dialog = app.screen
            self.assertIsInstance(dialog, T.Confirm)
            for ident in ("del-no", "del-yes"):
                button = dialog.query_one("#" + ident)
                self.assertGreater(button.region.width, 0)
                self.assertLessEqual(button.region.right, dialog.region.right)
                self.assertLessEqual(button.region.bottom, dialog.region.bottom)
            self.shot(app, "delete-small")
            await pilot.press("l")
            self.assertEqual(app.focused.id, "del-yes")
            await pilot.press("h")
            self.assertEqual(app.focused.id, "del-no")
            await pilot.press("enter")
            self.assertEqual(self.st.deleted, [])
            self.assertNotIsInstance(app.screen, T.Confirm)
        self.run_app(fn, size=(80, 24))

    def test_search_and_add(self):
        async def fn(app, pilot):
            await pilot.press("7")
            await self.settle(app, pilot, 2)
            await pilot.press(*"comet", "enter")
            await self.settle(app, pilot, 6)
            t = app.query_one("#search-list")
            self.assertEqual(t.get_row_at(0)[1], "Comet Drift")
            self.shot(app, "search")
            await pilot.press("enter")                                          # its request form
            await self.settle(app, pilot, 2)
            await pilot.click("#req-planbtn")
            await self.settle(app, pilot, 3)
            self.shot(app, "request")
            log = app.screen.query_one("#req-plan")
            self.assertTrue(any("Comet Drift" in str(ln) for ln in log.lines), [str(x) for x in log.lines])
            await pilot.click("#req-yes")
            await self.settle(app, pilot, 6)
            # it's in Radarr already (the fixture's 251): the request searches for it there, not through Seerr
            self.assertIn(("radarr", {"name": "MoviesSearch", "movieIds": [251]}), self.st.commands)
            self.assertEqual(self.st.seerr_requests, [])
        self.run_app(fn, size=(150, 44))

    def test_filter_and_sort(self):
        async def fn(app, pilot):
            await pilot.press("slash", *"paper")
            await self.settle(app, pilot, 2)
            tv = app.query_one("#tv-list")
            self.assertEqual([tv.get_row_at(i)[1] for i in range(tv.row_count)], ["Paper Moon Cafe"])
            await pilot.press("escape")
            await pilot.press("s")                                              # added -> size
            await self.settle(app, pilot, 2)
            self.assertEqual(app.sort["tv"], "size")
            self.assertEqual(tv.get_row_at(0)[1], "Starlight Harbor")          # 12 GB before 8 GB
        self.run_app(fn)


if __name__ == "__main__":
    unittest.main()

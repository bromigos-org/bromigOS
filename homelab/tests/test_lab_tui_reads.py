"""Late dashboard reads must survive shutdown and never replace newer results."""
import asyncio
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

try:
    from bromigos_homelab import tui
except ImportError:
    tui = None


READS = {
    "status": ("doc", "top", {"state": "empty", "configured": False, "cards": []}),
    "models": ("inv", "gpus", {"gpus": [], "servers": []}),
    "jobs": ("jobsdoc", "jobsum", {"jobs": [], "service": "fixture"}),
    "doctor": ("doctor_doc", "docsum", {"summary": {}, "findings": []}),
}


class Read:
    def __init__(self, kind, generation):
        self.data = dict(READS[kind][2], generation=generation)
        self.entered = asyncio.Event()
        self.release = threading.Event()


class ControlledSource:
    def __init__(self, kind, reads):
        self.kind, self.reads = kind, iter(reads)
        self.loop = asyncio.get_running_loop()

    def read(self, kind):
        if kind != self.kind:
            raise AssertionError(f"Unexpected fixture read: {kind}")
        read = next(self.reads)
        self.loop.call_soon_threadsafe(read.entered.set)
        if not read.release.wait(10):
            raise TimeoutError("Test did not release the fixture read")
        return read.data

    def status(self):
        return self.read("status")

    def inventory(self):
        return self.read("models")

    def jobs(self):
        return self.read("jobs")

    def doctor(self):
        return self.read("doctor")


if tui is not None:
    class ControlledApp(tui.LabApp):
        def __init__(self, source):
            super().__init__(source=source, interval=3600)
            self.thread_finished = {}
            self.close_read = None
            self.closed_while_stopped = False

        def on_mount(self, event):
            # Keep the real UI, but start reads explicitly and avoid timers/theme files.
            event.prevent_default()

        def run_worker(self, work, **kwargs):
            if not kwargs.get("thread"):
                return super().run_worker(work, **kwargs)
            loop = asyncio.get_running_loop()
            finished = asyncio.Event()

            def tracked():
                try:
                    return work()
                finally:
                    # A cancelled Worker's wait() does not wait for its thread.
                    loop.call_soon_threadsafe(finished.set)

            worker = super().run_worker(tracked, **kwargs)
            self.thread_finished[worker] = finished
            return worker

        async def _close_all(self):
            try:
                if self.close_read is not None:
                    kind, read, worker = self.close_read
                    self.close_read = None
                    self.closed_while_stopped = not self.is_running
                    await self.query_one(f"#{READS[kind][1]}").remove()
                    read.release.set()
                    await asyncio.wait_for(worker.wait(), 5)
                    await asyncio.wait_for(self.thread_finished[worker].wait(), 5)
            finally:
                await super()._close_all()


@unittest.skipIf(tui is None, "Textual is required")
class ReadLifecycleTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        home = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.dict(os.environ, {
            "HOME": home,
            "XDG_CONFIG_HOME": str(Path(home) / "config"),
            "XDG_CACHE_HOME": str(Path(home) / "cache"),
            "XDG_DATA_HOME": str(Path(home) / "data"),
            "XDG_RUNTIME_DIR": str(Path(home) / "run"),
            "DBUS_SESSION_BUS_ADDRESS": "disabled:",
            "BROMIGOS_HOMELAB_CONFIG": str(Path(home) / "homelab.toml"),
            "BROMIGOS_LAB_PROFILES": str(Path(__file__).resolve().parents[1] / "share/lab/profiles.toml"),
        }))

    async def late_read(self, kind):
        read = Read(kind, "late")
        app = ControlledApp(ControlledSource(kind, [read]))
        try:
            async with app.run_test(size=(100, 35)):
                worker = getattr(app, f"load_{kind}")()
                await asyncio.wait_for(read.entered.wait(), 5)
                app.close_read = kind, read, worker
            self.assertTrue(app.closed_while_stopped)
            self.assertIsNone(worker.error)
            self.assertIsNone(getattr(app, READS[kind][0]))
        finally:
            read.release.set()

    async def superseded_read(self, kind):
        old, fresh = Read(kind, "old"), Read(kind, "fresh")
        fresh.release.set()
        app = ControlledApp(ControlledSource(kind, [old, fresh]))
        try:
            async with app.run_test(size=(100, 35)) as pilot:
                first = getattr(app, f"load_{kind}")()
                await asyncio.wait_for(old.entered.wait(), 5)
                second = getattr(app, f"load_{kind}")()
                await asyncio.wait_for(second.wait(), 5)
                await pilot.pause()
                self.assertTrue(first.is_cancelled)
                self.assertEqual(getattr(app, READS[kind][0]), fresh.data)
                old.release.set()
                await asyncio.wait_for(app.thread_finished[first].wait(), 5)
                await pilot.pause()
                self.assertEqual(getattr(app, READS[kind][0]), fresh.data)
        finally:
            old.release.set()

    async def test_status_completes_during_shutdown(self):
        await self.late_read("status")

    async def test_models_complete_during_shutdown(self):
        await self.late_read("models")

    async def test_jobs_complete_during_shutdown(self):
        await self.late_read("jobs")

    async def test_doctor_completes_during_shutdown(self):
        await self.late_read("doctor")

    async def test_superseded_status_cannot_replace_fresh_data(self):
        await self.superseded_read("status")

    async def test_superseded_models_cannot_replace_fresh_data(self):
        await self.superseded_read("models")

    async def test_superseded_jobs_cannot_replace_fresh_data(self):
        await self.superseded_read("jobs")

    async def test_superseded_doctor_cannot_replace_fresh_data(self):
        await self.superseded_read("doctor")

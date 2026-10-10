"""The dashboard tree uses the same presets and resolver as the terminal plan."""
import os
from pathlib import Path
import unittest

os.environ["BROMIGOS_LAB_PROFILES"] = str(Path(__file__).resolve().parents[1] / "share/lab/profiles.toml")
try:
    from bromigos_homelab import tui, provision
except ImportError:
    tui = None


class Empty:
    def status(self):
        return {"state": "empty", "configured": False, "cards": []}

    def jobs(self):
        return {"jobs": []}


@unittest.skipIf(tui is None, "Textual is required")
class PickerTest(unittest.IsolatedAsyncioTestCase):
    async def test_presets_dependencies_and_toggle(self):
        app = tui.LabApp(source=Empty(), interval=3600)
        async with app.run_test(size=(100, 35)) as pilot:
            app.action_tab("provision")
            await pilot.pause()
            await pilot.click("#provision-advanced")
            await pilot.pause()
            self.assertEqual(app.provision_selected, provision.preset_selection(app.provision_cat, "advanced"))
            self.assertTrue({"argocd", "helm", "vault", "kubernetes"}.issubset(app.provision_selected))
            tree = app.query_one("#provision-tree", tui.Tree)
            helm = next(node for group in tree.root.children for node in group.children if node.data == "helm")
            tree.select_node(helm)
            await pilot.pause()
            self.assertIn("helm", app.provision_selected)  # Argo and Vault still depend on it.
            await pilot.click("#provision-core")
            await pilot.pause()
            self.assertEqual(app.provision_selected, provision.preset_selection(app.provision_cat, "core"))

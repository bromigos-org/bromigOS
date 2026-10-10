"""Colour validation, preserving prompt options and removing stale instant prompts."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'lib'))
from bromigos_prompt import generate, update, BEGIN, END


class MehshellColours(unittest.TestCase):
    def test_update_preserves_options_and_reloads_colours(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {
                'HOME': d, 'XDG_CONFIG_HOME': d+'/config', 'XDG_CACHE_HOME': d+'/cache'}):
            path = Path(d)/'config/mehshell/config'
            path.parent.mkdir(parents=True)
            path.write_text('style = classic\ngit = false\n')
            cache = Path(d)/'cache/mehshell-prompt-cache'
            cache.parent.mkdir()
            cache.write_text('old colours')
            palette = Path(d)/'palette.json'
            fixture = json.loads((ROOT/'live/tests/golden/mehshell/wick.palette.json').read_text())
            palette.write_text(json.dumps(fixture))
            update(palette, path)
            self.assertFalse(cache.exists())
            self.assertIn('style = classic\ngit = false\n', path.read_text())
            fixture['colors']['primary'] = '#123456'
            palette.write_text(json.dumps(fixture))
            update(palette, path)
            self.assertIn('color_39 = #123456', path.read_text())
            self.assertEqual(path.read_text().count(BEGIN), 1)
            self.assertEqual(path.read_text().count(END), 1)

    def test_rejects_colours_that_could_be_shell_code(self):
        fixture = json.loads((ROOT/'live/tests/golden/mehshell/wick.palette.json').read_text())
        fixture['colors']['primary'] = "#123456};id"
        with self.assertRaises(ValueError):
            generate(fixture)

    def test_each_theme_golden(self):
        for palette in sorted((ROOT/'live/tests/golden/mehshell').glob('*.palette.json')):
            with self.subTest(theme=palette.stem):
                expected = palette.with_name(palette.name.replace('.palette.json', '.config'))
                self.assertEqual(generate(json.loads(palette.read_text())), expected.read_text())

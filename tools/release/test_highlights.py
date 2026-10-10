"""Reviewed edge features survive long drafts and repeated release candidates."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import release

PAGE = '''# What's new
<!-- unreleased: v0.1.2 -->
## On edge
### New
- [Layouts](panels.md#layouts) keep the scene clear.
  Pick them in Customize.
- Media requests handle seasons and audio.
### Fixed
- Scanner colours follow the theme.
### Planned
- Provision a lab.
<!-- /unreleased -->
'''


class Highlights(unittest.TestCase):
    def test_wrapped_bullets_are_carried_but_plans_and_old_baselines_are_not(self):
        items = release.manual_highlights(PAGE, 'v0.1.2')
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0], dict(section='new', text='Layouts keep the scene clear. Pick them in Customize.'))
        self.assertNotIn('Provision', str(items))
        self.assertEqual(release.manual_highlights(PAGE, 'v0.1.3'), [])
        self.assertEqual(release.manual_highlights(PAGE, 'v0.1.1'), items)

    def test_long_no_model_fallback_keeps_the_oldest_feature(self):
        commits = [dict(subject=f'Feature {i}', group='Desktop') for i in range(60)]
        notes = release.fallback(commits)
        self.assertIn('Feature 59', notes['improved'])
        items = release.manual_highlights(PAGE, 'v0.1.2')
        notes = release.include_highlights(notes, items)
        self.assertIn(items[0]['text'], notes['new'])
        self.assertIn(items[-1]['text'], notes['fixed'])
        release.include_highlights(notes, items)
        self.assertEqual(notes['new'].count(items[0]['text']), 1)

    def test_release_moves_highlights_and_keeps_them_for_later_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'manual/src').mkdir(parents=True)
            (root / 'tools/release').mkdir(parents=True)
            page = root / 'manual/src/whats-new.md'
            page.write_text(PAGE + release.MARKER + '\n')
            (root / 'CHANGELOG.md').write_text('# Changes\n' + release.MARKER + '\n')
            items = release.reviewed_highlights(tmp, 'v0.1.2')
            plan = dict(version='0.1.3', tag='v0.1.3-rc1', kind='rc', rc=1,
                        since='v0.1.2', date='2026-10-10', bromigos=dict(base='a'*40, since='v0.1.2'))
            notes = dict(drafted_by='test', bromigos_commits=60, bromigos_changelog='',
                         bromigos_highlights=items, bromigos=release.include_highlights(release.fallback([]), items))
            (root / 'plan.json').write_text(json.dumps(plan))
            (root / 'notes.json').write_text(json.dumps(notes))
            a = SimpleNamespace(plan=str(root / 'plan.json'), notes=str(root / 'notes.json'))
            with patch.object(release, 'ROOT', tmp), patch.object(release, 'HERE', str(root / 'tools/release')), patch.object(release, 'bump_cargo'):
                release.write_cmd(a)
            self.assertNotIn('<!-- unreleased:', page.read_text())
            self.assertIn('## 0.1.3', page.read_text())
            self.assertIn(items[0]['text'], page.read_text())
            self.assertEqual(release.reviewed_highlights(tmp, 'v0.1.2'), items)
            self.assertEqual(release.reviewed_highlights(tmp, 'v0.1.3'), [])
            # A feature added after the draft must not be erased by writing stale notes.
            page.write_text(PAGE.replace('- Media requests', '- Another feature.\n- Media requests') + release.MARKER)
            with patch.object(release, 'ROOT', tmp), patch.object(release, 'HERE', str(root / 'tools/release')), patch.object(release, 'bump_cargo'):
                with self.assertRaises(SystemExit):
                    release.write_cmd(a)
            self.assertIn('Another feature', page.read_text())

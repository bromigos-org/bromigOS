"""The standalone package's dependency boundary and pinned AUR release recipe."""
import hashlib
import importlib.util
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]

class StandaloneTest(unittest.TestCase):
    def test_runtime_dependencies_do_not_pull_in_the_desktop(self):
        text = (ROOT / 'packaging/bromigos-lab/PKGBUILD').read_text()
        depends = re.search(r'^depends=\((.*)\)$', text, re.M)[1]
        self.assertEqual(depends, "'python' 'python-textual'")
        desktop = (ROOT / 'packaging/bromigos-homelab/PKGBUILD').read_text()
        self.assertIn("'bromigos-lab'", re.search(r'^depends=\((.*)\)$', desktop, re.M)[1])
        self.assertNotIn('install -Dm0755', desktop)
        self.assertNotIn('install -Dm0644 -t "$lib/', desktop)

    def renderer(self):
        spec = importlib.util.spec_from_file_location('aur_lab', ROOT / 'packaging/ci/prepare-aur-lab.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module.render

    def test_recipe_has_exact_tag_and_checksum_without_vcs_versioning(self):
        data = b'public source release'
        for tag, version in [('bromigos-lab-v0.1.0', '0.1.0'), ('v0.1.3', '0.1.3')]:
            text = self.renderer()(tag, data)
            self.assertIn('_tag=' + tag, text)
            self.assertIn('pkgver=' + version, text)
            self.assertIn(hashlib.sha256(data).hexdigest(), text)
            self.assertNotIn('SKIP', text)
            self.assertNotIn('pkgver()', text)
            self.assertNotIn('@VERSION@', text)
            self.assertIn('Maintainer: bromigOS <packages@bromigos.org>', text)
            self.assertIn('packaging/install-lab.sh', text)

    def test_unpinned_or_invalid_source_names_are_refused(self):
        for tag in ('main', 'latest', 'v0.1.0-rc1', 'bromigos-lab-v1', 'v1.2.3;echo bad', '../v1.2.3'):
            with self.assertRaises(ValueError): self.renderer()(tag, b'')

    def test_desktop_catalog_precedes_the_standalone_fallback(self):
        from bromigos_homelab import catalog
        paths = catalog.candidates_paths()
        self.assertLess(paths.index(str(Path(catalog.SHARE) / 'homelab/lab/models.toml')),
                        paths.index('/usr/share/bromigos-lab/models.toml'))

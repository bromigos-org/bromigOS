"""Guard live drawing code against fixed colours. Audit plugins with --plugins DIR.

Numeric geometry, light intensities, masks and the den's retinted art shades are
explicit exceptions. UI colours have palette tokens, including warn and danger.
"""
import ast
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
# Exact numeric tuples, per file. These are not RGB; new ones need a reason here.
ALLOW = {
    'constellation.py': ({(0, .08, 0)}, 'hub position'),
    'fireflies.py': ({(.0021, .0034, .0013)}, 'flow frequencies'),
    'gadgets.py': ({(.13, .3, .04), (.18, .3, .23), (.24, 0, .2), (0, .17, .5),
                    (.62, .48, .3), (.05, 1, .95), (0, .86, .6), (0, .9, 0),
                    (.2, .56, .5), (.05, .5, .5)}, 'model geometry and rings'),
    'glkit.py': ({(.012, .05, .012), (.03, .13, .025), (0, .035, 0), (.04, .12, .04),
                  (.02, .05, .02), (.6, 1, .66), (.084, .159, .105), (.78, 1, .74),
                  (0, 0, 1, 0), (0, 1, 0), (1, 0, 0), (0, 0, 1)},
                 'central retinted den shades, clip rectangle and rotation axes'),
    'holoview.py': ({(0, .48, 0)}, 'camera target'),
    'overlays.py': ({(.25, .4, .5, .4), (0, 0, 1, 0)}, 'reveal durations and effect uniforms'),
    'ops_deck.py': ({(.3, .18, 0), (.6, .06, 0)}, 'stage node positions'),
    'plugins.py': ({(.45, .6, .5, .4), (.55, .3, .7, .5)}, 'demo load and network readings'),
    'scene.py': ({(.3, .59, .11), (0, 0, 1, 0)}, 'luma weights and TV transform'),
    'swarm_deck.py': ({(0, .25, 0), (.5, .5, .3, .4), (1, .85, 1, 1),
                      (.5, .45, .25, .35), (.8, .7, .45, .55), (.7, .6, .3, .8)},
                     'warp offset and four independent lamp intensities'),
    'tv.py': ({(0, 0, 1, 0)}, 'TV crop transform'),
    'zoomcam.py': ({(1, 0, 0)}, 'zoom and pan state'),
}
# A match pattern for recolouring older plugin shaders, never emitted as a colour.
LEGACY_PATTERN = ('glkit.py', 'mix(c, vec3(0.0, 0.03, 0.0), plate)')
HEX = re.compile(r'#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?\b')
DRAW = {'line': 2, 'polyline': 1, 'rect': 4, 'brackets': 4, 'arc': 5, 'text': 3}


def numbers(node):
    if not isinstance(node, (ast.Tuple, ast.List)) or len(node.elts) not in (3, 4):
        return None
    if all(isinstance(x, ast.Constant) and type(x.value) in (int, float) for x in node.elts):
        return tuple(x.value for x in node.elts)


def python_issues(text, filename):
    tree = ast.parse(text)
    issues = set()
    allowed = ALLOW.get(filename, (set(), ''))[0]
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if HEX.search(n.value):
                issues.add((n.lineno, 'hex colour'))
            if shader_issues(n.value) and (filename, n.value) != LEGACY_PATTERN:
                issues.add((n.lineno, 'embedded shader colour; use THEME_TOKEN'))
        if isinstance(n, ast.Assign) and numbers(n.value) is not None:
            names = ' '.join(ast.unparse(t) for t in n.targets)
            if re.search(r'(?:rgb|rgba|color|colour|green|phos|soft|amber|danger|tint)', names, re.I):
                issues.add((n.lineno, 'colour assignment; use a palette token'))
        v = numbers(n)
        if v is not None and all(0 <= x <= 1 for x in v) and any(v) and v not in allowed:
            issues.add((n.lineno, 'fixed RGB-like tuple; use a token or document non-colour geometry'))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            name = n.func.attr
            if name in ('set_source_rgb', 'set_source_rgba'):
                literal = all(isinstance(x, ast.Constant) and type(x.value) in (int, float) for x in n.args[:3])
                # White here is an alpha mask, never a displayed colour.
                mask = filename in ('glkit.py', 'shipmask.py') and [getattr(x, 'value', None) for x in n.args] == [1, 1, 1, 1]
                if len(n.args) >= 3 and literal and not mask:
                    issues.add((n.lineno, 'Cairo colour; use col(token, alpha)'))
            if name in DRAW and len(n.args) > DRAW[name] and numbers(n.args[DRAW[name]]) is not None:
                issues.add((n.lineno, 'drawing colour; use col(token)'))
    return sorted(issues)


def shader_issues(text):
    # Float literals in vec3/vec4: scalar zero and -1 are clears and sentinels.
    # The few vector literals below are math, not emitted light.
    allowed = {(0.3, .59, .11)}    # luma coefficients (Rec. 601)
    issues = []
    text = re.sub(r'//[^\n]*|/\*.*?\*/', lambda m: '\n' * m[0].count('\n'), text, flags=re.S)
    for m in re.finditer(r'\bvec([34])\s*\(([^()]*)\)', text):
        try:
            v = tuple(float(x.strip()) for x in m[2].split(','))
        except ValueError:
            continue
        if (len(v) == 1 and v[0] in (0, -1)) or v in allowed:
            continue
        # Drift script's vec4 strokes are geometry, covered by the exact shader below.
        issues.append((text[:m.start()].count('\n') + 1, v))
    return issues


def audit(directory, plugins=False):
    issues = []
    for p in directory.rglob('*'):
        if p.suffix == '.py':
            # Plugins don't inherit engine geometry exceptions by sharing its filename.
            findings = python_issues(p.read_text(), '' if plugins else p.name)
        elif p.suffix == '.lua':
            findings = [(p.read_text()[:m.start()].count('\n') + 1, 'literal Lua colour')
                        for m in re.finditer(r'(?:#[0-9a-fA-F]{6}\b|&H[0-9a-fA-F]{6}&)', p.read_text())]
        elif p.suffix in ('.glsl', '.frag', '.vert'):
            findings = shader_issues(p.read_text())
            # Original Drift-script glyph strokes, not colours. Only that array is exempt.
            if p.name == 'rain.glsl':
                lines = p.read_text().splitlines()
                start = next(i for i, s in enumerate(lines, 1) if 'const vec4 G[' in s)
                end = next(i for i, s in enumerate(lines, 1) if i > start and ');' in s)
                findings = [(i, v) for i, v in findings if not start <= i <= end]
        else:
            continue
        issues.extend(f'{p}:{i}: {why}' for i, why in findings)
    return issues


class PaletteLiterals(unittest.TestCase):
    def test_live_drawings_use_palette_tokens(self):
        issues = audit(ROOT / 'live') + audit(ROOT / 'shaders')
        homelab = ROOT.parent / 'homelab' / 'live'
        if homelab.is_dir():
            issues += audit(homelab)
        self.assertEqual(issues, [], '\n'.join(issues))

    def test_shader_tokens_resolve_in_raw_plugin_sources(self):
        from types import SimpleNamespace as NS
        path = ROOT / 'live/glkit.py'
        node = next(n for n in ast.parse(path.read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'theme_consts')
        palette = NS(version=lambda _: 1, rgb=lambda _: (.9, .4, .1), is_wick=lambda: False)
        ns = dict(T=palette, _SHADES={}, _COMPUTED={})
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), ns)
        resolve = ns['theme_consts']
        # Program can resolve raw tokens without recolouring already-resolved art.
        source = 'c = THEME_PRIMARY; vec3 GLASS = vec3(0.01,0.02,0.03);'
        result = resolve(source, legacy=False)
        self.assertIn('vec3(0.9000, 0.4000, 0.1000)', result)
        self.assertIn('vec3(0.01,0.02,0.03)', result)
        palette.rgb = lambda _: (.1, .6, .9)
        self.assertNotEqual(result, resolve(source, legacy=False))

    def test_guard_rejects_new_colour_constants_and_drawing_arguments(self):
        for code in ('GREEN=(0.2, 1., 0.1)', 'RGB=(57,255,20)', 'INK="#39ff14"',
                     'b.text("HUD", 0, 0, (57, 255, 20, 255))',
                     'cr.set_source_rgba(0, 1, 0, .8)',
                     'b.line((0,0), (1,1), (0,0,0,1))'):
            with self.subTest(code=code):
                self.assertTrue(python_issues(code, 'new_deck.py'))
        self.assertTrue(shader_issues('c += vec3(0.2, 1.0, 0.1);'))
        self.assertTrue(shader_issues('c += vec3(1.0);'))
        self.assertFalse(python_issues('b.text("HUD",0,0,col("soft"))', 'new_deck.py'))
        self.assertFalse(shader_issues('c += THEME_SOFT;'))


if __name__ == '__main__':
    if '--plugins' in sys.argv:
        paths = sys.argv[sys.argv.index('--plugins') + 1:]
        found = [i for p in paths for i in audit(Path(p), plugins=True)]
        print('\n'.join(found) if found else 'PASS: plugins use palette tokens')
        sys.exit(bool(found))
    unittest.main()

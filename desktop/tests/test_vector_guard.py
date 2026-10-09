"""VECTOR's emergency switch: Settings may switch him off at any time, and switches him back on
only from the confirm dialog of the VECTOR page (pages/vector.py's docstring says why). This
reads the Settings code and fails on any other path to `bromigos-holo on` (or its old name,
`shell on`): a second call site, a call outside the confirm callback, an exported action, a
command-line flag, a URL handler, a flip of the switch that turns him on by itself.

    python -m unittest discover -s desktop/tests
"""
import ast
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(os.path.dirname(HERE), "settings")


def sources():
    for root, _dirs, files in os.walk(SETTINGS):
        if "__pycache__" in root:
            continue
        for f in files:
            if f.endswith(".py") or f == "bromigos-settings":
                p = os.path.join(root, f)
                with open(p) as fh:
                    yield p, fh.read()


ARMS = {"shell", "switch", "vector", "bromigos-holo", "holo"}     # what comes before "on" in an argv that arms him


def _lists_with_shell_on(tree):
    """Every list/tuple literal that starts with "on" (the page's _holo puts the launcher in
    front), or holds "on" right after the launcher (HOLO, "bromigos-holo") or after "shell",
    "switch" or "vector": an argv switching him back on."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            vals = [e.value if isinstance(e, ast.Constant) else
                    ("holo" if isinstance(e, ast.Name) and "HOLO" in e.id.upper() else None) for e in node.elts]
            if vals[:1] == ["on"] or any(vals[i] in ARMS and vals[i + 1] == "on" for i in range(len(vals) - 1)):
                out.append(node)
    return out


class GuardTest(unittest.TestCase):
    def test_one_call_site_inside_the_confirm_callback(self):
        found = []
        for path, text in sources():
            tree = ast.parse(text)
            for fn in ast.walk(tree):
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for lst in _lists_with_shell_on(fn):
                        found.append((os.path.basename(path), fn.name, lst.lineno))
            # nothing at module level either
            top = sum(len(_lists_with_shell_on(n)) for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.ClassDef)))
            self.assertEqual(top, 0, path)
            self.assertNotRegex(text, r"(shell|switch|vector|holo) on['\"]", path)   # no "… on" command string
        # nested functions are walked twice (the class's and the method's): unique by place
        self.assertEqual({(f, fn) for f, fn, _ in found}, {("vector.py", "_rearm_confirmed")}, found)

    def test_the_callback_is_only_handed_to_confirm(self):
        with open(os.path.join(SETTINGS, "pages", "vector.py")) as f:
            tree = ast.parse(f.read())
        uses = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "_rearm_confirmed" and isinstance(node.ctx, ast.Load):
                uses.append(node)
        self.assertEqual(len(uses), 1, "the re-arm callback is referenced from one place only")
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "confirm" and any(a is uses[0] for a in n.args)]
        self.assertEqual(len(calls), 1, "…and that place is the argument of ctx.confirm(…)")
        # and `_rearm` (which opens the dialog) is called from one place: the switch's flip
        opens = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "_rearm"]
        self.assertEqual(len(opens), 1)

    def test_flipping_the_switch_on_only_asks(self):
        """A flip to on puts the switch back off and opens the dialog; nothing else."""
        with open(os.path.join(SETTINGS, "pages", "vector.py")) as f:
            tree = ast.parse(f.read())
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_switch_flipped")
        src = ast.unparse(fn)
        self.assertIn("set_quiet(False)", src)
        self.assertIn("self._rearm()", src)
        self.assertNotIn("_rearm_confirmed", src)
        self.assertLess(src.index("set_quiet(False)"), src.index("self._rearm()"))

    def test_no_exported_actions_flags_or_handlers(self):
        for path, text in sources():
            for pattern in (r"\badd_action\b", r"SimpleAction", r"add_action_entries", r"install_action",
                            r"register_uri|x-scheme-handler|scheme_handler", r"--arm|--rearm|shell-on"):
                self.assertIsNone(re.search(pattern, text), f"{path}: {pattern}")

    def test_reset_never_touches_the_switch(self):
        with open(os.path.join(SETTINGS, "pages", "vector.py")) as f:
            tree = ast.parse(f.read())
        reset = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "reset")
        code = ast.unparse(ast.Module(body=[b for b in reset.body if not (isinstance(b, ast.Expr) and
                                                                         isinstance(b.value, ast.Constant))],
                                      type_ignores=[]))      # its code, not its docstring
        for word in ("shell", "switch", "_rearm", "_holo(['on'", "_holo(['off'"):
            self.assertNotIn(word, code)
        self.assertEqual(_lists_with_shell_on(reset), [])

    def test_confirm_defaults_to_cancel(self):
        with open(os.path.join(SETTINGS, "bromigos_settings", "context.py")) as f:
            text = f.read()
        body = text[text.index("def confirm("):text.index("def choose_file(")]
        self.assertIn('d.set_default_response("cancel")', body)
        self.assertIn('d.set_close_response("cancel")', body)


if __name__ == "__main__":
    unittest.main()

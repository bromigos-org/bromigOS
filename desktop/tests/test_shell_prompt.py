"""Choose prompts and source zsh only in a temporary HOME."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT/'desktop/bin/bromigos-shell'
ZSH = ROOT/'desktop/zsh/bromigos.zsh'
MIGRATION = ROOT/'migrations/20261010120000-shell-prompt.sh'


class PromptChoice(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.bin = self.home/'bin'
        self.bin.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME=str(self.home/'config'),
                        XDG_STATE_HOME=str(self.home/'state'), XDG_CACHE_HOME=str(self.home/'cache'),
                        ZDOTDIR=str(self.home), BROMIGOS_BANNER='off',
                        PATH=str(self.bin)+':/usr/bin:/bin')
        for engine in ['mehshell', 'starship']:
            script = self.bin/engine
            script.write_text('#!/bin/sh\nprintf "typeset -g selected='+engine+'\\n"\n')
            script.chmod(0o755)

    def run_cli(self, *args, ok=True):
        result = subprocess.run([str(CLI), *args, '--json'], env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0 if ok else 1, result.stderr+result.stdout)
        return json.loads(result.stdout)

    def shell(self):
        code = 'source "$1"; print -r -- "${selected:-none}"; print -r -- "$PROMPT"'
        return subprocess.check_output(['zsh', '-f', '-c', code, 'zsh', str(ZSH)], env=self.env, text=True)

    def test_switch_and_invalid_choice(self):
        startup = self.home/'.zshrc'
        startup.write_text('# personal shell\n')
        for engine in ['mehshell', 'starship', 'none', 'mehshell']:
            self.assertEqual(self.run_cli('prompt', engine)['prompt'], engine)
            self.assertEqual(self.shell().splitlines()[0], engine if engine != 'none' else 'none')
            self.assertEqual(startup.read_text(), '# personal shell\n')
        self.run_cli('prompt', 'invalid', ok=False)
        self.assertEqual(self.run_cli()['prompt'], 'mehshell')

    def test_unmanaged_shell_does_not_initialise_engine(self):
        self.assertFalse(self.run_cli()['managed'])
        self.assertEqual(self.shell().splitlines()[0], 'none')

    def test_missing_engine_does_not_change_choice(self):
        self.run_cli('prompt', 'none')
        (self.bin/'starship').unlink()
        self.run_cli('prompt', 'starship', ok=False)
        self.assertEqual(self.run_cli()['prompt'], 'none')

    def test_new_install_and_existing_startup(self):
        subprocess.run(['sh', str(MIGRATION)], env=self.env, check=True)
        self.assertEqual(self.run_cli()['prompt'], 'mehshell')
        self.assertIn('source /usr/share/bromigos/default/zsh/bromigos.zsh', (self.home/'.zshrc').read_text())
        config = self.home/'config/bromigos/shell.toml'
        config.unlink()
        (self.home/'.zshrc').write_text('# existing Starship setup\n')
        subprocess.run(['sh', str(MIGRATION)], env=self.env, check=True)
        self.assertFalse(config.exists())
        self.assertEqual((self.home/'.zshrc').read_text(), '# existing Starship setup\n')

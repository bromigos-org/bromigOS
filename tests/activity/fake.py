"""A stand-in machine for `bromigos activity`'s tests: a root folder (BROMIGOS_ROOT), a home,
and stand-in commands first on PATH. Nothing here starts a real systemd unit, asks for a
password, or reads or changes the real machine.

  systemd-run   notes its command line in FAKE/calls, then runs the unit's command detached,
                in its own session, as a transient unit would (its pid in FAKE/<unit>.pid);
                FAKE/refuse makes it fail as systemd does when a unit can't start
  systemctl     notes its command line; `is-system-running` answers FAKE/system-state
  sudo, pkexec  note their command line and refuse: a test never becomes root
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "lib"))

import bromigos_activity as A  # noqa: E402

SCRIPT = REPO / "bin/bromigos-activity"
FIXTURES = HERE.parent / "fixtures"
NOW = 1794264000000          # 2026-11-09 22:40 UTC (a fixed clock, when a test wants one)

STUBS = {
    "systemd-run": r'''#!/bin/sh
echo "systemd-run $*" >> "$FAKE/calls"
unit=""
while [ $# -gt 0 ]; do
  case "$1" in
    --unit=*) unit=${1#--unit=} ;;
    --setenv=*) export "${1#--setenv=}" ;;
    --) shift; break ;;
  esac
  shift
done
if [ -e "$FAKE/refuse" ]; then
  echo "Failed to start transient service unit: Unit $unit was already loaded or has a fragment file." >&2
  exit 1
fi
cd /
setsid "$@" </dev/null >"$FAKE/$unit.out" 2>&1 &
echo $! > "$FAKE/$unit.pid"
exit 0
''',
    "systemctl": r'''#!/bin/sh
echo "systemctl $*" >> "$FAKE/calls"
[ "$1" = "is-system-running" ] && cat "$FAKE/system-state" 2>/dev/null
exit 0
''',
    "sudo": '#!/bin/sh\necho "sudo $*" >> "$FAKE/calls"\nexit 1\n',
    "pkexec": '#!/bin/sh\necho "pkexec $*" >> "$FAKE/calls"\nexit 1\n',
}


class FakeMachine:
    def __init__(self, systemd=False, server=False):
        self.tmp = Path(tempfile.mkdtemp(prefix="bromigos-activity-"))
        self.root, self.home, self.bin, self.fake = (self.tmp / n for n in ("root", "home", "bin", "fake"))
        for d in (self.root, self.home, self.bin, self.fake):
            d.mkdir()
        for name, body in STUBS.items():
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)
        if systemd:                                   # "systemd runs here": the stand-in systemd-run is used
            (self.root / "run/systemd/system").mkdir(parents=True)
        if server:                                    # bromigOS Server's state subvolume is there
            (self.root / "var/lib/bromigos/server").mkdir(parents=True)
        self.environ = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "DISPLAY")
                        and not k.startswith(("BROMIGOS_", "XDG_"))}
        self.environ.update(HOME=str(self.home), BROMIGOS_ROOT=str(self.root), FAKE=str(self.fake),
                            PATH=f"{self.bin}:{os.environ.get('PATH', '/usr/bin:/bin')}", PYTHONDONTWRITEBYTECODE="1")

    def close(self):
        for p in self.fake.glob("*.pid"):             # no stand-in unit outlives its test
            try:
                os.killpg(int(p.read_text()), 9)
            except (OSError, ValueError):
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def env(self, **more):
        return A.Env(dict(self.environ, **{k: str(v) for k, v in more.items()}))

    @property
    def jobs(self):
        return Path(self.env().jobs_dir())

    def script(self, body, name="job"):
        """An executable sh script: what a job runs."""
        p = self.tmp / name
        p.write_text("#!/bin/sh\n" + body)
        p.chmod(0o755)
        return str(p)

    def cli(self, *args, env=None, timeout=60):
        """`bromigos activity ARGS` to its end: (exit status, stdout, stderr)."""
        r = subprocess.run([sys.executable, str(SCRIPT), *args], env=dict(self.environ, **(env or {})),
                           capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, cwd=self.tmp)
        return r.returncode, r.stdout, r.stderr

    def popen(self, *args, env=None):
        return subprocess.Popen([sys.executable, str(SCRIPT), *args], env=dict(self.environ, **(env or {})),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL,
                                cwd=self.tmp)

    def on_disk(self):
        """{id: the record as the file has it}."""
        return {p.stem: json.loads(p.read_text()) for p in sorted(self.jobs.glob("*.json"))}

    def listed(self, *args):
        code, out, err = self.cli("list", "--all", "--json", *args)
        assert code == 0, err
        return json.loads(out)["jobs"]

    def calls(self):
        p = self.fake / "calls"
        return p.read_text().splitlines() if p.exists() else []

    def unit_pid(self, job_id):
        return int((self.fake / f"{A.unit_name(job_id)}.pid").read_text())

    def wait(self, what, timeout=20, words="it didn't happen in time"):
        """Poll until what() is true; return its value."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            got = what()
            if got:
                return got
            time.sleep(0.02)
        raise AssertionError(words)

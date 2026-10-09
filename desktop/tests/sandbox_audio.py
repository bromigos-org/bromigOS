"""A PipeWire nobody hears: pipewire, wireplumber and pipewire-pulse in a runtime directory
and home of their own, with every device monitor off (no ALSA card is opened, no Bluetooth
endpoint registered, no camera touched) and no D-Bus, session or system. Its devices are
null sinks and a remapped source made with pactl; its apps are pacat streams of silence.
Nothing reaches the sound server of the desktop it runs on.

    with AudioSandbox() as a:
        a.env                       # HOME, XDG_RUNTIME_DIR … for pactl, wpctl and bromigos sound
        a.sink("speakers", "Speakers"); a.source("mic", "Desk microphone", "speakers")
        a.app("Music Player")
"""
import os
import shutil
import signal
import subprocess
import tempfile
import time

WIREPLUMBER_SANDBOX = """
# the sandbox's session manager: no device monitors, no D-Bus
wireplumber.profiles = {
  main = {
    monitor.alsa = disabled
    monitor.alsa-midi = disabled
    monitor.bluez = disabled
    monitor.bluez-midi = disabled
    monitor.bluez.seat-monitoring = disabled
    monitor.libcamera = disabled
    monitor.v4l2 = disabled
    support.dbus = disabled
    support.reserve-device = disabled
    support.portal-permissionstore = disabled
    support.logind = disabled
  }
}
"""


def available():
    return all(shutil.which(t) for t in ("pipewire", "wireplumber", "pipewire-pulse", "pactl", "pacat"))


class AudioSandbox:
    def __init__(self, keep=False, run_dir=None, home=None):
        """run_dir/home: share another sandbox's (the nested Hyprland's), else its own."""
        self.keep = keep
        self.tmp = tempfile.mkdtemp(prefix="bsa-", dir="/tmp")
        self.run_dir = run_dir or os.path.join(self.tmp, "run")
        self.home = home or os.path.join(self.tmp, "home")
        os.makedirs(self.run_dir, mode=0o700, exist_ok=True)
        conf = os.path.join(self.home, ".config", "wireplumber", "wireplumber.conf.d")
        os.makedirs(conf, exist_ok=True)
        with open(os.path.join(conf, "90-sandbox.conf"), "w") as f:
            f.write(WIREPLUMBER_SANDBOX)
        self.env = {"HOME": self.home, "XDG_RUNTIME_DIR": self.run_dir, "PATH": os.environ.get("PATH", "/usr/bin"),
                    "XDG_CONFIG_HOME": os.path.join(self.home, ".config"),
                    "XDG_STATE_HOME": os.path.join(self.home, ".local", "state"),
                    "XDG_DATA_HOME": os.path.join(self.home, ".local", "share"),
                    "DBUS_SESSION_BUS_ADDRESS": "disabled:", "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/nonexistent",
                    "PIPEWIRE_RUNTIME_DIR": self.run_dir, "PULSE_RUNTIME_PATH": os.path.join(self.run_dir, "pulse"),
                    "LANG": "C.UTF-8", "DISABLE_RTKIT": "1"}
        self.procs = []

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    def _spawn(self, argv):
        log = open(os.path.join(self.tmp, os.path.basename(argv[0]) + ".log"), "w")
        p = subprocess.Popen(argv, env=self.env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        self.procs.append(p)
        return p

    def pactl(self, *args, check=True):
        r = subprocess.run(["pactl", *args], env=self.env, capture_output=True, text=True, timeout=10)
        if check and r.returncode != 0:
            raise RuntimeError(f"pactl {' '.join(args)}: {r.stderr.strip()}")
        return r.stdout.strip()

    def start(self):
        self._spawn(["pipewire"])
        self._wait(lambda: os.path.exists(os.path.join(self.run_dir, "pipewire-0")), "pipewire")
        self._spawn(["wireplumber"])
        self._spawn(["pipewire-pulse"])
        self._wait(lambda: os.path.exists(os.path.join(self.run_dir, "pulse", "native")), "pipewire-pulse")
        self._wait(lambda: subprocess.run(["pactl", "info"], env=self.env, capture_output=True,
                                          timeout=5).returncode == 0, "pactl info")

    def _wait(self, fn, what, timeout=15):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if fn():
                return
            time.sleep(0.1)
        raise RuntimeError(f"the sandbox's {what} didn't start (logs in {self.tmp})")

    def sink(self, name, description):
        self.pactl("load-module", "module-null-sink", f"sink_name={name}",
                   f"sink_properties=\"device.description='{description}'\"")
        self._wait(lambda: name in self.pactl("list", "short", "sinks"), f"sink {name}")

    def source(self, name, description, of_sink):
        self.pactl("load-module", "module-remap-source", f"master={of_sink}.monitor", f"source_name={name}",
                   f"source_properties=\"device.description='{description}'\"")
        self._wait(lambda: name in self.pactl("list", "short", "sources"), f"source {name}")

    def app(self, name, sink=None):
        """A stream of silence from an app called `name` (a pacat), playing until stop()."""
        argv = ["pacat", "--playback", "--raw", f"--client-name={name}", f"--stream-name={name} playback"]
        if sink:
            argv.append(f"--device={sink}")
        log = open(os.path.join(self.tmp, "pacat.log"), "a")
        p = subprocess.Popen(argv, env=self.env, stdin=open("/dev/zero", "rb"), stdout=log, stderr=log,
                             start_new_session=True)
        self.procs.insert(0, p)
        self._wait(lambda: name in self.pactl("list", "sink-inputs"), f"app {name}")
        return p

    def stop(self):
        for p in self.procs:
            if p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except OSError:
                    pass
        for p in self.procs:
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except OSError:
                    pass
        if not self.keep:
            shutil.rmtree(self.tmp, ignore_errors=True)


if __name__ == "__main__":
    with AudioSandbox(keep=True) as a:
        a.sink("speakers", "Desk speakers")
        a.sink("headphones", "USB headphones")
        a.source("mic", "Desk microphone", "speakers")
        a.app("Music Player")
        print(a.pactl("--format=json", "list", "sinks")[:1500])
        print("---")
        print(a.pactl("--format=json", "list", "sink-inputs")[:1500])
        print("---")
        print(a.pactl("--format=json", "info"))
        print(a.tmp)

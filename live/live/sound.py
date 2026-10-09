"""Short, quiet cues through PipeWire. Mute state lives in a state file so the
keybind works whether or not the daemon is up."""
import os
import shutil
import subprocess

HERE = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SOUNDS = os.path.join(HERE, "sounds")
STATE = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), "bromigos-live")
MUTE = os.path.join(STATE, "muted")


def muted():
    return os.path.exists(MUTE)


def toggle_mute():
    os.makedirs(STATE, exist_ok=True)
    if muted():
        os.remove(MUTE)
        return False
    open(MUTE, "w").close()
    return True


class Sound:
    def __init__(self, cfg):
        self.cfg = cfg
        self.player = shutil.which("pw-play") or shutil.which("paplay")

    def _target(self):
        """Optional output node (sounds.sink or $BROMIGOS_LIVE_SINK), e.g. a headset or a test null sink."""
        t = os.environ.get("BROMIGOS_LIVE_SINK") or self.cfg.get("sounds", {}).get("sink", "")
        return [f"--target={t}"] if t else []

    def play_file(self, path, delete=False, gain=None):
        """Play an arbitrary wav (codec voice); honours mute and the volume."""
        s = self.cfg.get("sounds", {})
        if not s.get("enabled", True) or muted() or not self.player:
            return
        g = float(self.cfg.get("codec", {}).get("voice_gain", 1.6)) if gain is None else gain
        vol = max(0.0, min(1.0, float(s.get("volume", 0.3)) * g))
        if os.path.basename(self.player) == "pw-play":
            cmd = [self.player, f"--volume={vol:.3f}", "--media-role=Communication"] + self._target() + [path]
        else:
            cmd = [self.player, f"--volume={int(vol * 65536)}", path]
        if delete:
            cmd = ["sh", "-c", 'f="$1"; shift; "$@"; rm -f "$f"', "sh", path] + cmd
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            pass

    def play(self, cue):
        s = self.cfg.get("sounds", {})
        if not s.get("enabled", True) or muted() or not self.player:
            return
        name = s.get(cue) or f"{cue}.wav"
        path = name if os.path.isabs(name) else os.path.join(SOUNDS, name)
        if not os.path.exists(path):
            return
        vol = max(0.0, min(1.0, float(s.get("volume", 0.3))))
        if os.path.basename(self.player) == "pw-play":
            cmd = [self.player, f"--volume={vol:.3f}", "--media-role=Notification"] + self._target() + [path]
        else:
            cmd = [self.player, f"--volume={int(vol * 65536)}", path]
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            pass

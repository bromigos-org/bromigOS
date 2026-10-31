#!/usr/bin/env python3
"""Speak the voice guide's lines in VECTOR's voice: one small Opus clip per line of
lib/guide/lines.toml, in lib/guide/clips/, and their manifest (docs/voice-guide.md).

    tools/voice/make-clips.py              speak the new and changed lines; remove stale clips
    tools/voice/make-clips.py --all        speak every line again
    tools/voice/make-clips.py --check      no voice needed: fail when a line has no clip, or its
                                           clip says other words (CI runs this)

How the voice is made: this starts VECTOR's own voice server (bromigos-vector's
holo/voice_server.py, from --vector) as a process of its own, on its own socket in --work,
in the voice environment (--python, the one `bromigos-holo setup voice` builds). It always
speaks with the package's voice.json, so the clips have VECTOR's designed caretaker voice
(voices/vector-ref-A.wav) and never a user's personal cast. The engine is the homelab's
voice service ("lab", found the way VECTOR finds it: targets.toml, homelab.toml or the private
overlay, all read at run time); --engines lab,qwen lets this machine's Qwen3-TTS speak when
the lab can't. Kokoro is never used: it isn't his designed voice.

It needs ffmpeg with libopus. The clips are mono Opus at 28 kb/s, tagged with their line's
id and the hash of its words.
"""
import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
sys.path.insert(0, os.path.join(REPO, "lib"))
import bromigos_guide as G  # noqa: E402

DESIGNED = {"lab", "qwen"}            # the engines that speak with the designed reference
BITRATE = "28k"

SERVER = r"""
import json, os, sys
vector, cache, engines = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
sys.path.insert(0, vector)
os.chdir(vector)
import holo.voice_server as vs
vs.CONF = os.path.join(vs.HERE, "voice.json")        # the package's: the designed voice, never a user's cast
vs.CACHE = cache                                      # its wavs stay in the work folder
vs.Server.order = lambda self: (engines[0], engines[1:])
_warm = vs.Server.warm_tts
def warm_tts(self, local=False):
    if (local or engines[0] == "qwen") and "qwen" not in engines:
        return {"ok": True, "ready": False}           # no model loads on this GPU unless asked
    return _warm(self, local)
vs.Server.warm_tts = warm_tts
s = vs.Server()
lab = s.cfg.setdefault("lab", {})
lab["first_audio_timeout_s"] = max(15, lab.get("first_audio_timeout_s", 0))   # a batch can wait
lab["timeout_s"] = max(15, lab.get("timeout_s", 0))
s.cfg["exit_after_seconds"] = 600
s.serve()
"""


def ask(sock, req, timeout=180):
    c = socket.socket(socket.AF_UNIX)
    c.settimeout(timeout)
    c.connect(sock)
    c.sendall((json.dumps(req) + "\n").encode())
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = c.recv(65536)
        if not chunk:
            break
        buf += chunk
    c.close()
    return json.loads(buf.decode())


def start_server(args, work):
    sock = os.path.join(work, "voice.sock")
    env = dict(os.environ, BROMIGOS_VOICE_SOCK=sock, PYTHONDONTWRITEBYTECODE="1")
    log = open(os.path.join(work, "voice-server.log"), "w")
    p = subprocess.Popen([args.python, "-c", SERVER, args.vector, os.path.join(work, "cache"),
                          json.dumps(args.engines)], env=env, stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    t0 = time.monotonic()
    while time.monotonic() - t0 < 120:
        if p.poll() is not None:
            sys.exit(f"the voice server stopped; its log: {log.name}")
        if os.path.exists(sock):
            try:
                pong = ask(sock, {"op": "ping"}, timeout=10)
                if "lab" in args.engines and not pong.get("lab"):
                    p.terminate()
                    sys.exit("no lab voice service is configured here (voice.json lab.url, targets.toml or "
                             "homelab.toml's voice capability). Use --engines qwen to speak on this machine.")
                return p, sock
            except OSError:
                pass
        time.sleep(0.3)
    p.terminate()
    sys.exit(f"the voice server didn't start in 2 minutes; its log: {log.name}")


def encode(wav, out, key, text):
    tmp = out + ".part.opus"
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", wav, "-map_metadata", "-1",
                    "-ac", "1", "-c:a", "libopus", "-b:a", BITRATE, "-application", "voip",
                    "-fflags", "+bitexact", "-flags:a", "+bitexact",
                    "-metadata", f"BROMIGOS_GUIDE_ID={key}",
                    "-metadata", f"BROMIGOS_GUIDE_TEXT_SHA256={G.text_hash(text)}", tmp], check=True)
    os.replace(tmp, out)


def seconds(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return round(float(r.stdout.strip()), 2)
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="only check the clips against the catalogue (no voice)")
    ap.add_argument("--all", action="store_true", help="speak every line again, not only new and changed ones")
    ap.add_argument("--dir", default=os.path.join(REPO, "lib", "guide"), help="the guide's folder (lines.toml, clips/)")
    ap.add_argument("--vector", default=next((d for d in ("/usr/lib/bromigos/vector",) if os.path.isdir(d)), None),
                    help="VECTOR's tree, with holo/voice_server.py (default: bromigos-vector's)")
    ap.add_argument("--python", default=os.path.expanduser("~/.local/share/bromigos/venv-tts/bin/python"),
                    help="the voice environment's Python")
    ap.add_argument("--engines", default="lab", help="engines to try in order: lab, qwen (default: lab)")
    ap.add_argument("--work", help="a folder for the server's socket, log and wavs (default: a new temporary one)")
    args = ap.parse_args()

    if args.check:
        bad = G.problems(args.dir)
        for b in bad:
            print("✗", b)
        n = len(G.clips(args.dir))
        if bad:
            sys.exit(f"{len(bad)} problem(s) with the voice guide's clips; run tools/voice/make-clips.py")
        size = sum(os.path.getsize(os.path.join(args.dir, "clips", f)) for f in os.listdir(os.path.join(args.dir, "clips"))
                   if f.endswith(".opus"))
        print(f"voice guide ok: {n} clips for {len(G.catalogue(args.dir))} lines, {size / 1024:.0f} KiB")
        return

    args.engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    if not args.engines or set(args.engines) - DESIGNED:
        sys.exit("--engines takes lab and qwen only: the other engines don't speak in VECTOR's designed voice")
    if not args.vector or not os.path.isfile(os.path.join(args.vector, "holo", "voice_server.py")):
        sys.exit("no VECTOR tree: install bromigos-vector, or give --vector a checkout of bromigos-org/vector")
    if not os.access(args.python, os.X_OK):
        sys.exit(f"no voice environment at {args.python}: `bromigos-holo setup voice` builds it, or give --python")
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg is needed, with libopus")

    cdir = os.path.join(args.dir, "clips")
    os.makedirs(cdir, exist_ok=True)
    old = G.manifest(args.dir).get("clips", {})
    want = G.clips(args.dir)
    todo = []
    for key, lid, vals, text in want:
        m = old.get(key)
        name = G.clip_file(key, text)
        if args.all or not m or m.get("text_sha256") != G.text_hash(text) or not os.path.isfile(os.path.join(cdir, name)):
            todo.append((key, lid, vals, text))
    ref = os.path.join(args.vector, "voices", "vector-ref-A.wav")
    voice = {"ref": "vector-ref-A", "ref_sha256": hashlib.sha256(open(ref, "rb").read()).hexdigest()}
    clips = {k: v for k, v in old.items() if k in {w[0] for w in want}}

    if todo:
        work = args.work or tempfile.mkdtemp(prefix="bromigos-guide-")
        os.makedirs(work, exist_ok=True)
        print(f"speaking {len(todo)} line(s); the server's log: {os.path.join(work, 'voice-server.log')}")
        proc, sock = start_server(args, work)
        try:
            for key, lid, vals, text in todo:
                r = ask(sock, {"op": "tts", "text": text, "role": "main"})
                if r.get("error"):
                    sys.exit(f"{key}: the voice server said: {r['error']}")
                if r.get("engine") not in args.engines:
                    sys.exit(f"{key}: spoken by {r.get('engine')!r}, not {', '.join(args.engines)}: stopping, "
                             "so no clip has a different voice")
                name = G.clip_file(key, text)
                out = os.path.join(cdir, name)
                encode(r["wav"], out, key, text)
                clips[key] = {"file": name, "text": text, "text_sha256": G.text_hash(text),
                              "engine": r["engine"], "seconds": seconds(out)}
                print(f"  {key:44s} {r['engine']:5s} {os.path.getsize(out) / 1024:5.1f} KiB  {text}")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    keep = {c["file"] for c in clips.values()}
    for f in os.listdir(cdir):
        if f.endswith(".opus") and f not in keep:
            os.remove(os.path.join(cdir, f))
            print("  removed", f)
    doc = {"format": 1, "voice": voice, "codec": f"opus mono {BITRATE}b/s",
           "clips": {k: clips[k] for k in sorted(clips)}}
    with open(os.path.join(cdir, "manifest.json"), "w") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
        f.write("\n")
    bad = G.problems(args.dir)
    for b in bad:
        print("✗", b)
    if bad:
        sys.exit(1)
    size = sum(os.path.getsize(os.path.join(cdir, f)) for f in keep)
    print(f"voice guide ok: {len(clips)} clips, {size / 1024:.0f} KiB")


if __name__ == "__main__":
    main()

"""What the welcome tours do (bromigos welcome, the desktop's; bromigos welcome-console,
bromigOS Server's): one module, so the window and the terminal behave alike and neither
keeps a setting of its own. Every change goes the usual way: `bromigos setup SECTION`,
`bromigos setup homelab`, packages through polkit (pkexec), the BRODEC machine agent's own
files. Nothing here opens a terminal.

  gpu_vram_gib()                the biggest GPU's memory, GiB (bromigos hw detect), or 0
  local_model()                 the lab catalog's best chat model for this GPU, with its download
                                size: {name, quant, repo, weights, disk_gib, pull} or None
  lab_brains()                  the lab's model servers already in homelab.toml: [{name, url}]
  find_lab()                    Find my lab, without writing: {hosts: [{name, address, offers}], brains, error}
  connect_lab()                 Find my lab, writing what it found to homelab.toml
  use_lab_file(path)            a homelab.toml (or a Field Kit stick's lab connection) to use
  provision_plan()              bromigos-lab's reviewed plan for making this computer the lab (text)
  set_brain(kind, …)            bromigos setup vector …
  hello(name)                   VECTOR's first words through his brain (and his voice, when he has one)
  brain()                       his brain when it answers: {url, model, key} (his own settings), or None
  ask(question, context, b)     one question to his brain about a tour step: (ok, his answer, or why not)
  run_lines(argv, on_line)      a long step (a package, a model, a voice), line by line
  machine_*, Pairing, Enroll     BRODEC's machine agent (brodec-machine): its package and root's
                                machine.toml through polkit; `brodec-machine pair --json` (and a lab
                                bridge's `brodec-lab pair --json`) as events; enroll's question
  qr_png(text, path) / qr_text(text)   a QR code as a picture (the window) or half-blocks (a terminal)
"""
import glob
import json
import os
import re
import shutil
import subprocess
import time

HOME = os.path.expanduser("~")
PLAY_STORE = "https://play.google.com/store/apps/details?id=org.bromigos.brodec"
CATALOG = "/usr/share/bromigos/homelab/lab/models.toml"
LLM_TYPES = ("litellm", "ollama", "openai", "vllm", "llamacpp", "llama.cpp")
PHONE_CAN = [
    "Chat with VECTOR, from anywhere",
    "Approve the fixes VECTOR proposes for this computer",
    "Restart, shut down or update this computer",
    "Open chat-style terminal sessions on it",
]


def run(argv, timeout=60, input=None):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, input=input)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, "", str(e)


def run_lines(argv, on_line, timeout=7200):
    """Run a long step, handing each line of its output to on_line; returns (ok, last lines)."""
    tail = []
    try:
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    except OSError as e:
        return False, str(e)
    start = time.monotonic()
    for line in p.stdout:
        line = line.rstrip()
        tail = (tail + [line])[-8:]
        on_line(line)
        if time.monotonic() - start > timeout:
            p.kill()
            break
    return p.wait() == 0, "\n".join(tail)


def plain_error(text):
    """A command's last words, made readable (no traces, no paths of ours)."""
    lines = [l for l in (text or "").strip().splitlines() if l.strip() and not l.startswith(("Traceback", "  File"))]
    return (lines[-1] if lines else "it stopped without saying why")[:240]


# ── this computer ───────────────────────────────────────────────────────────────────────
def hardware():
    code, out, _ = run(["bromigos", "hw", "detect", "--json"], timeout=30)
    try:
        return json.loads(out)
    except ValueError:
        return {}


def gpu_vram_gib(hw=None):
    hw = hardware() if hw is None else hw
    best = 0.0
    for g in (hw.get("detection") or {}).get("gpus") or []:
        v = g.get("vram_gib") or (g.get("vram_mib") or 0) / 1024 or (g.get("vram_bytes") or 0) / 2 ** 30
        best = max(best, float(v or 0))
    return best


def gpu_vendor(hw=None):
    hw = hardware() if hw is None else hw
    gs = (hw.get("detection") or {}).get("gpus") or []
    v = (gs[0].get("vendor") if gs else "") or ""
    return v.lower()


def local_model(vram_gib=None, vendor=None):
    """The catalog's best chat model for this GPU (bromigos-homelab's catalog), and what it
    downloads; None without a GPU of 8 GB or more, or without the catalog."""
    vram_gib = gpu_vram_gib() if vram_gib is None else vram_gib
    if vram_gib < 8:
        return None
    try:
        import sys
        sys.path.insert(0, "/usr/lib/bromigos/homelab")
        from bromigos_homelab import catalog as C
        pick = C.pick("llm", vram_gib=vram_gib, vendor=(vendor or gpu_vendor() or "nvidia"))
        best = pick.get("best") or {}
    except Exception:
        return None
    if not best:
        return None
    disk = None
    try:
        import tomllib
        with open(os.environ.get("BROMIGOS_LAB_CATALOG", CATALOG), "rb") as f:
            cat = tomllib.load(f)
        for m in cat.get("model", []):
            if m.get("id") == best.get("model"):
                for v in m.get("variant", []) if isinstance(m.get("variant"), list) else []:
                    if v.get("id") == best.get("variant"):
                        disk = v.get("disk_gib") or v.get("weights_gib")
    except Exception:
        pass
    weights = best.get("weights") or best.get("repo")
    quant = re.search(r"(UD-)?Q\d+_K(_[MSL])?", best.get("quant") or "")
    return {"name": best.get("name"), "quant": best.get("quant"), "repo": best.get("repo"), "weights": weights,
            "disk_gib": float(disk) if disk else float(best.get("mem_gib") or 0),
            "pull": f"hf.co/{weights}" + (f":{quant.group(0)}" if quant else ""),
            "speed": best.get("speed_text")}


def ollama_package(vendor=None):
    v = (vendor or gpu_vendor() or "").lower()
    return "ollama-cuda" if "nvidia" in v else ("ollama-rocm" if "amd" in v else "ollama")


def install_local_brain(model, on_line):
    """Ollama (through polkit: the system's own password prompt) and the model, downloaded;
    then VECTOR's brain points at it. Returns (ok, words)."""
    if not shutil.which("ollama"):
        on_line("Installing Ollama (it asks for your password)…")
        ok, tail = run_lines(["pkexec", "pacman", "-S", "--noconfirm", "--needed", ollama_package()], on_line)
        if not ok:
            return False, "Ollama couldn't be installed: " + plain_error(tail)
        run_lines(["pkexec", "systemctl", "enable", "--now", "ollama.service"], on_line)
    on_line(f"Downloading {model['name']} ({model['disk_gib']:.0f} GB)…")
    ok, tail = run_lines(["ollama", "pull", model["pull"]], on_line)
    if not ok:
        return False, f"{model['name']} couldn't be downloaded: " + plain_error(tail)
    code, out, err = set_brain("ollama", model=model["pull"])
    return (code == 0), ("" if code == 0 else "VECTOR's brain couldn't be set: " + plain_error(err or out))


# ── the lab ─────────────────────────────────────────────────────────────────────────────
def homelab_toml():
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config"), "bromigos/homelab.toml")


def lab_brains(sources=None):
    """Model servers the lab offers: [{name, url}] from homelab.toml's sources (or the given ones)."""
    if sources is None:
        try:
            import tomllib
            with open(homelab_toml(), "rb") as f:
                sources = tomllib.load(f).get("source", [])
        except (OSError, ValueError):
            sources = []
    out = []
    for s in sources:
        t = str(s.get("type", "")).lower()
        url = s.get("endpoint") or s.get("url") or ""
        if t in LLM_TYPES and url:
            url = url.rstrip("/")
            out.append({"name": s.get("name") or t, "url": url if url.endswith("/v1") else url + "/v1", "type": t})
    return out


def find_lab():
    """Find my lab (bromigos setup homelab --find): it reads what this computer already knows
    of the network (it never scans), checks those devices, and writes nothing."""
    code, out, err = run(["bromigos", "setup", "homelab", "--find", "--yes", "--json"], timeout=240)
    try:
        doc = json.loads(out)
    except ValueError:
        return {"hosts": [], "brains": [], "error": "Looking for your lab didn't work: " + plain_error(err or out)}
    lab = doc.get("lab") or {}
    hosts = []
    for h in lab.get("hosts", []):
        svcs = h.get("services") or []
        if not svcs:
            continue
        offers = sorted({str(s.get("name") or s.get("type")) for s in svcs})
        hosts.append({"name": h.get("name") or h.get("address"), "address": h.get("address"), "offers": offers})
    found = doc.get("found") or []
    return {"hosts": hosts, "brains": lab_brains(found), "new": len(doc.get("new") or []), "error": None,
            "machines": len(lab.get("hosts", []))}


def connect_lab():
    code, out, err = run(["bromigos", "setup", "homelab", "--find", "--yes"], timeout=300)
    return code == 0, ("" if code == 0 else "Connecting your lab didn't work: " + plain_error(err or out))


def use_lab_file(path):
    code, out, err = run(["bromigos", "setup", "homelab", "--homelab", path], timeout=120)
    return code == 0, ("" if code == 0 else "That file didn't work: " + plain_error(err or out))


def provision_plan(repo=None):
    """bromigos-lab's reviewed plan for this computer as the lab (it changes nothing)."""
    repo = repo or os.path.join(HOME, "lab")
    code, out, err = run(["bromigos", "lab", "provision", "plan", "--repo", repo, "--preset", "core"], timeout=180)
    return code == 0, (out or err).strip()


# ── VECTOR ──────────────────────────────────────────────────────────────────────────────
def set_brain(kind, url=None, key_file=None, model=None):
    args = ["bromigos", "setup", "vector", "--vector", {"lab": "openai", "service": "openai"}.get(kind, kind)]
    if url:
        args += ["--base-url", url]
    if key_file:
        args += ["--api-key-file", key_file]
    if model:
        args += ["--model", model]
    return run(args, timeout=120)


def hello(name=""):
    """VECTOR's first words, through his brain and, when he has a voice, out loud: (ok, words)."""
    who = f" to {name}" if name else ""
    code, out, err = run(["bromigos-holo", "ask", f"Say hello{who} in one short, warm sentence: this is the first "
                          "time you two talk, on a new bromigOS computer."], timeout=120)
    text = (out or "").strip()
    if code == 0 and text:
        return True, text.splitlines()[-1][:300]
    return False, "VECTOR couldn't reach his brain: " + plain_error(err or out)


VECTOR_ROOT = os.environ.get("BROMIGOS_VECTOR_ROOT") or "/usr/lib/bromigos/vector"


def _vector_toml():
    c = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")
    for p in (os.path.join(c, "bromigos/vector/vector.toml"), os.path.join(c, "bromigos/holo/vector.toml"),
              "/etc/bromigos/vector/vector.toml", os.path.join(VECTOR_ROOT, "vector.toml")):
        try:
            import tomllib
            with open(p, "rb") as f:
                return tomllib.load(f).get("llm") or {}
        except (OSError, ValueError):
            continue
    return {}


def brain(timeout=3):
    """VECTOR's brain, when it answers: {"url", "model", "key"}, or None. Where it is comes from
    his own settings, read his way (bromigos-vector's holo/vector/llm.py: vector.toml's [llm],
    then targets.toml and his fallbacks), else vector.toml alone. BROMIGOS_VECTOR_BRAIN names a
    base URL instead (tests: a stand-in), or "none". The key is only ever sent to that server."""
    import urllib.request
    forced = os.environ.get("BROMIGOS_VECTOR_BRAIN")
    if forced == "none":
        return None
    url = model = key = None
    if forced:
        url, model, key = forced.rstrip("/"), os.environ.get("BROMIGOS_VECTOR_MODEL") or "vector", "none"
    else:
        try:
            import sys
            if VECTOR_ROOT not in sys.path:
                sys.path.append(VECTOR_ROOT)
            from holo.vector import llm
            url, model, key = llm.base(), llm.model(), llm.key()
        except Exception:
            cfg = _vector_toml()
            url = (cfg.get("base_url") or "").rstrip("/") or None
            model = cfg.get("model") or "qwen3:8b"
            try:
                with open(os.path.expanduser(cfg.get("api_key_file") or "~/.local/share/bromigos/litellm-key")) as f:
                    key = f.read().strip() or "none"
            except OSError:
                key = "none"
    if not url:
        return None
    try:
        req = urllib.request.Request(url + "/models", headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status != 200:
                return None
    except Exception:
        return None
    return {"url": url, "model": model, "key": key}


def ask(question, context="", b=None, timeout=45):
    """Ask VECTOR's brain one question about the tour's step (context: the step, in words).
    (True, his answer) or (False, what went wrong and what to do), never an exception."""
    import urllib.error
    import urllib.request
    b = b or brain()
    if not b:
        return False, "VECTOR has no brain connected yet. Give him one on the VECTOR step, or later in Settings › VECTOR."
    system = ("You are VECTOR, the AI of bromigOS, helping someone through the welcome tour on their new computer. "
              "Answer in two or three short, plain sentences, kindly, without jargon. Only give a command if they ask "
              "for one. The step they're on: " + (context or "the welcome tour"))
    body = json.dumps({"model": b["model"], "messages": [{"role": "system", "content": system},
                                                         {"role": "user", "content": question.strip()[:1000]}],
                       "max_tokens": 400, "temperature": 0.4, "stream": False}).encode()
    req = urllib.request.Request(b["url"] + "/chat/completions", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {b['key']}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            doc = json.loads(r.read().decode("utf-8", "replace"))
        text = (doc.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    except TimeoutError:
        return False, f"VECTOR didn't answer in {timeout} seconds. Ask again, or ask him later from the desktop."
    except urllib.error.HTTPError as e:
        return False, f"VECTOR's brain said no ({e.code}). Check his brain in Settings › VECTOR, then ask again."
    except Exception as e:
        if "timed out" in str(e):
            return False, f"VECTOR didn't answer in {timeout} seconds. Ask again, or ask him later from the desktop."
        return False, "VECTOR couldn't reach his brain. Check the network, or his brain in Settings › VECTOR."
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    if not text:
        return False, "VECTOR had nothing to say to that. Ask it another way."
    return True, text[:1200]


def voice(tier, on_line):
    ok, tail = run_lines(["bromigos", "setup", "voice", "--voice", tier], on_line)
    return ok, ("" if ok else "His voice couldn't be set up: " + plain_error(tail))


# ── the phone (BRODEC's machine agent: brodec-machine; docs/MACHINE_JOBS.md in brodec,
#    "Pairing from a setup screen") ────────────────────────────────────────────────────
MACHINE_TOML = os.environ.get("BRODEC_MACHINE_TOML") or "/etc/brodec-machine/machine.toml"   # tests: elsewhere
MACHINE_EXAMPLE = "/usr/share/brodec-machine/machine.toml.example"


def machine_installed():
    return bool(shutil.which("brodec-machine"))


def machine_package():
    """The package that carries the agent: brodec-machine on its own (no GTK) when the
    repositories have it, else brodec-desktop, which carries it on a desktop."""
    code, _, _ = run(["pacman", "-Si", "brodec-machine"], timeout=20)
    return "brodec-machine" if code == 0 else "brodec-desktop"


def machine_config_ready():
    return os.path.exists(MACHINE_TOML)


FIELDKIT_ENGINE = "/usr/lib/bromigos/fieldkit/fieldkit-engine"


def _config_cmd():
    """root's machine.toml (the agent runs only once it exists). On bromigOS Server and a Field
    Kit stick, Field Kit's file: no jobs, its console's Herdr workspace and the
    phone's shells, machine controls on (restart, shut down; update on Server)
    (docs/fieldkit-vector.md, "Pair with BRODEC"). Elsewhere the package's example."""
    fieldkit = (f"[ -x {FIELDKIT_ENGINE} ] && {{ [ -x /usr/lib/bromigos/server/bromigos-server ] || "
                "[ -e /etc/bromigos-fieldkit/medium ]; }")
    return (f"[ -e {MACHINE_TOML} ] || {{ if {fieldkit}; then {FIELDKIT_ENGINE} brodec-setup; "
            f"else install -D -m 0644 {MACHINE_EXAMPLE} {MACHINE_TOML}; fi; }}")


def machine_install(on_line, package=None):
    """The agent's package and root's machine.toml, the usual way: polkit asks for the
    password once, in its own window."""
    pkg = package or machine_package()
    ok, tail = run_lines(["pkexec", "sh", "-c", f"pacman -S --noconfirm --needed {pkg} && {_config_cmd()}"], on_line)
    return ok, ("" if ok else "BRODEC's helper couldn't be installed: " + plain_error(tail))


def machine_config(on_line):
    """Only root's machine.toml (the package is there already), through polkit."""
    ok, tail = run_lines(["pkexec", "sh", "-c", _config_cmd()], on_line)
    return ok, ("" if ok else "Pairing couldn't be allowed on this computer: " + plain_error(tail))


def machine_config_sudo_cmd():
    """The same for a terminal (the console tour, where sudo asks)."""
    return ["sudo", "sh", "-c", _config_cmd()]


class Pairing:
    """`brodec-machine pair --json --start` (or `pkexec brodec-lab pair --json` for a lab's
    VECTOR bridge), its JSON events handed to on_event(dict) from a reader thread:
    code (qr, qr_svg, qr_text, user_code_display), expired, waiting, paired, failed,
    cancelled. cancel() stops the watching (SIGTERM); the agent keeps its code."""

    def __init__(self, argv, on_event):
        import threading
        self.argv, self.on_event, self.proc = argv, on_event, None
        self.done = False
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            self.proc = subprocess.Popen(self.argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        except OSError as e:
            self._emit({"event": "failed", "code": "agent_failed", "message": str(e)})
            return
        for line in self.proc.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict) and ev.get("event"):
                self._emit(ev)
        rc = self.proc.wait()
        if not self.done:          # it ended without saying how
            err = (self.proc.stderr.read() or "").strip()
            self._emit({"event": "cancelled"} if rc == 130 else
                       {"event": "failed", "code": "agent_failed", "message": err or f"it stopped ({rc})"})

    def _emit(self, ev):
        if ev["event"] in ("paired", "failed", "cancelled"):
            self.done = True
        self.on_event(ev)

    def cancel(self):
        import signal
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)


def machine_pair_argv(timeout=900):
    return ["brodec-machine", "pair", "--json", "--start", "--timeout", str(timeout)]


def lab_bridge_available():
    """This computer runs a lab's VECTOR bridge (brodec-lab): it can be paired too."""
    return bool(shutil.which("brodec-lab"))


def lab_pair_argv(gui=True):
    return [("pkexec" if gui else "sudo"), "brodec-lab", "pair", "--json"]


def pairing_words(ev):
    """An event in plain words, for the status line (code and paired are drawn instead)."""
    e = ev.get("event")
    if e == "expired":
        return "That code ran out. A new one is coming…"
    if e == "waiting":
        return ev.get("message") or "Waiting for BRODEC's helper…"
    if e == "failed":
        if ev.get("code") == "no_capability_file":
            return "Pairing isn't allowed on this computer yet: press Allow pairing (it asks for your password)."
        if ev.get("code") == "timeout":
            return "No phone paired in time. Press Try again to show a new code."
        return "Pairing stopped: " + plain_error(ev.get("message") or "") + " Press Try again."
    if e == "cancelled":
        return "Pairing stopped. Press Try again to show the code."
    return ""


class Enroll:
    """`brodec-machine enroll` through root (pkexec in the window): it describes each phone
    that asked (In BRODEC: ALLOW THIS PHONE) and asks [y/N]. ask(text) -> bool answers it
    (called from the reader thread: the window waits on its own dialog); done(ok, words)."""

    def __init__(self, ask, done, user=None):
        import threading
        self.ask, self.done_cb = ask, done
        self.user = user or os.environ.get("USER") or ""
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            p = subprocess.Popen(["pkexec", "brodec-machine", "enroll", "--user", self.user], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=0)
        except OSError as e:
            self.done_cb(False, str(e))
            return
        buf, said, since = "", [], []
        while True:
            ch = p.stdout.read(1)
            if not ch:
                break
            buf += ch
            if buf.endswith("[y/N] "):          # the phone's description, then the question
                yes = bool(self.ask("\n".join(since + [buf[:-len("[y/N] ")].strip()]).strip()))
                p.stdin.write("y\n" if yes else "n\n")
                p.stdin.flush()
                buf, since = "", []
            elif ch == "\n":
                if buf.strip():
                    said.append(buf.strip())
                    since.append(buf.strip())
                buf = ""
        rc = p.wait()
        words = " ".join(said[-3:])
        self.done_cb(rc == 0, words or ("Done." if rc == 0 else "It didn't work (the password window was closed?)."))


def qr_png(text, path, scale=8):
    code, _, err = run(["qrencode", "-o", path, "-s", str(scale), "-m", "4", "-l", "M", text])
    return code == 0


def qr_text(text):
    """The QR as half-blocks with its quiet zone (two rows of modules a line), or None."""
    code, out, _ = run(["qrencode", "-t", "UTF8", "-m", "2", "-l", "M", text])
    return out.rstrip("\n") if code == 0 and out.strip() else None

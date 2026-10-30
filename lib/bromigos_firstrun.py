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
  run_lines(argv, on_line)      a long step (a package, a model, a voice), line by line
  machine_*                     BRODEC's machine agent (brodec-machine, in brodec-desktop): installed,
                                install, start, pair code, paired
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
MACHINE_DATA = os.environ.get("BRODEC_MACHINE_DATA") or os.path.join(HOME, ".local/share/brodec-machine")
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


def voice(tier, on_line):
    ok, tail = run_lines(["bromigos", "setup", "voice", "--voice", tier], on_line)
    return ok, ("" if ok else "His voice couldn't be set up: " + plain_error(tail))


# ── the phone (BRODEC's machine agent) ──────────────────────────────────────────────────
def machine_installed():
    return bool(shutil.which("brodec-machine"))


def machine_install(on_line):
    """brodec-desktop (it carries the agent), the usual package way: polkit asks for the password."""
    ok, tail = run_lines(["pkexec", "pacman", "-S", "--noconfirm", "--needed", "brodec-desktop"], on_line)
    return ok, ("" if ok else "BRODEC's helper couldn't be installed: " + plain_error(tail))


def machine_start():
    code, out, err = run(["systemctl", "--user", "enable", "--now", "brodec-machine.service"], timeout=60)
    return code == 0, ("" if code == 0 else "BRODEC's helper didn't start: " + plain_error(err or out))


def _read(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def machine_code():
    """The pairing code the agent shows while it waits ({user_code, qr, expires_at_ms, …}), or None."""
    c = _read(os.path.join(MACHINE_DATA, "pair-code.json"))
    if not c or c.get("expires_at_ms", 0) < time.time() * 1000:
        return None
    c["pretty"] = "-".join(re.findall(".{1,4}", re.sub(r"[^A-Za-z0-9]", "", c.get("user_code", "")).upper()))
    return c


def machine_paired():
    """The pairing, once the phone confirmed it ({name, owner, …}), or None."""
    p = _read(os.path.join(MACHINE_DATA, "pairing.json"))
    return p if p and not p.get("revoked_at") else None


def lab_bridge_code():
    """The lab's VECTOR bridge's pairing code, when the lab says it's waiting for one
    (bromigos lab bridge pair-code --json; a lab without it: None)."""
    code, out, _ = run(["bromigos", "lab", "bridge", "pair-code", "--json"], timeout=20)
    try:
        c = json.loads(out) if code == 0 else None
    except ValueError:
        c = None
    return c if c and c.get("qr") else None


def qr_png(text, path, scale=8):
    code, _, err = run(["qrencode", "-o", path, "-s", str(scale), "-m", "4", "-l", "M", text])
    return code == 0


def qr_text(text):
    """The QR as half-blocks with its quiet zone (two rows of modules a line), or None."""
    code, out, _ = run(["qrencode", "-t", "UTF8", "-m", "2", "-l", "M", text])
    return out.rstrip("\n") if code == 0 and out.strip() else None

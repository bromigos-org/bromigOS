#!/usr/bin/env python3
"""The lab console against a real lab: read-only first, then one voice line and one image
through the queue, with their notifications. Not part of the unit tests (it needs a lab).

    dbus-run-session -- python3 homelab/tests/e2e_lab.py OUT.json

Run it under dbus-run-session: the notifications go to a stand-in daemon on that private
bus (recorded, never shown on a desktop). The queue's service runs here, in the foreground
(never the user's systemd unit). Before each job it reads the GPU; the image job waits in
the queue until the GPU has the VRAM it needs plus the voice service's reserve. After the
image, what ComfyUI loaded for it is unloaded again (POST /free). The voice service is only
asked to speak; nothing stops, restarts or reconfigures anything.

Results land where the user's would: ~/Pictures/bromigos/lab/<kind>/ ($BROMIGOS_LAB_OUT).
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "lib"))
os.environ["BROMIGOS_LAB_NO_SYSTEMD"] = "1"            # the user's systemd is never asked

from bromigos_homelab import console, doctor, jobqueue as Q, labmodels  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "e2e-lab.json"
LAB = os.path.join(ROOT, "bin", "bromigos-lab")
res = {"t": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "checks": [], "jobs": {}}


def check(ok, what, detail=""):
    res["checks"].append({"ok": bool(ok), "what": what, "detail": detail})
    print(f"{'pass' if ok else 'FAIL'}  {what}" + (f"  ({detail})" if detail else ""), flush=True)
    return ok


def main():
    bus = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    if not bus or f"/run/user/{os.getuid()}/bus" in bus:
        sys.exit("run me under dbus-run-session (the notifications must stay on a private bus)")
    tmp = tempfile.mkdtemp(prefix="bromigos-lab-e2e-")
    notes = os.path.join(tmp, "notifications.jsonl")
    nd = subprocess.Popen([sys.executable, os.path.join(HERE, "notifyd.py"), notes], stdout=subprocess.PIPE, text=True)
    nd.stdout.readline()

    # ---------------------------------------------------------------- read-only
    t0 = time.time()
    st = console.status()
    check(st["configured"] and st["cards"], f"lab status: {len(st['cards'])} cards in {time.time() - t0:.1f} s",
          ", ".join(f"{c['id']}={c['state']}" for c in st["cards"]))
    ids = {c["id"] for c in st["cards"]}
    check({"nodes", "gpus", "services"} <= ids, "nodes, GPUs and services are on the console")
    t0 = time.time()
    dr = doctor.run()
    check(dr["findings"], f"lab doctor: {dr['summary']} in {time.time() - t0:.1f} s")
    check(all(f.get("fix") for f in dr["findings"] if f["status"] in ("warn", "fail")), "every problem has a fix")
    inv = labmodels.inventory()
    check(inv["servers"], f"lab models: {len(inv['gpus'])} GPUs, {len(inv['servers'])} servers")
    res["read_only"] = {"cards": {c["id"]: c["state"] for c in st["cards"]}, "doctor": dr["summary"]}

    # ---------------------------------------------------------------- the queue
    svc = subprocess.Popen([sys.executable, LAB, "serve"], stdout=open(os.path.join(tmp, "serve.log"), "w"),
                           stderr=subprocess.STDOUT, env=dict(os.environ, BROMIGOS_LAB_BY="e2e"))
    for _ in range(50):
        if Q.service_state() == "running":
            break
        time.sleep(0.2)
    check(Q.service_state() == "running", "the queue's service runs (in the foreground, not systemd)")
    try:
        before = Q.gpu_view()
        check(before and not before.get("error"), "the GPU before: " + (
            f"{before['free'] / 1024:.1f} of {before['total'] / 1024:.1f} GiB free, ComfyUI holds "
            f"{before['holds'] / 1024:.1f}, queue {before['running']}+{before['pending']}" if before else "no view"))
        res["gpu_before"] = before

        # a voice line, sampling the GPU while the voice service speaks (its working memory)
        low = [before["free"] if before else 0]
        stop = threading.Event()

        def sample():
            while not stop.is_set():
                v = Q.gpu_view()
                if v and not v.get("error"):
                    low[0] = min(low[0], v["free"])
                stop.wait(0.15)
        th = threading.Thread(target=sample, daemon=True)
        th.start()
        vj = Q.submit("voice", text="The relays are lit. The lab is listening, and the queue is clear.", by="e2e")
        vj = wait(vj["id"], 180)
        stop.set()
        th.join(2)
        voice_peak = (before["free"] - low[0]) if before else None
        res["jobs"]["voice"] = vj
        res["voice_working_mib"] = voice_peak
        ok = check(vj["state"] == "succeeded", f"voice line: {vj['state']}", vj.get("why") or "")
        if ok:
            w = vj["outputs"][0]
            with wave.open(w) as f:
                secs = f.getnframes() / f.getframerate()
            check(secs > 1.5 and w.startswith(Q.out_root()), f"the WAV: {secs:.1f} s, in {os.path.dirname(w)}")
        check(voice_peak is not None, f"the voice service's working memory while it spoke: {voice_peak} MiB")

        # an image, gated on VRAM by the queue
        need = Q.need_mib("image")
        v = Q.gpu_view()
        res["gate_before_image"] = {"view": v, "need_mib": need, "reserve_mib": Q.voice_reserve_mib(),
                                    "decision": Q.gate("image", v)}
        check(True, f"the gate: needs {need} MiB + {Q.voice_reserve_mib()} for the voice; "
                    f"{(v['free'] + v['holds']) if v else '?'} can be had -> {Q.gate('image', v)}")
        ij = Q.submit("image", prompt="A small brass relay mast on a hill at dusk, a thin green signal light at its "
                                      "top, painterly, no text", by="e2e", aspect="1:1",
                      options={"resolution": 1024})
        ij = wait(ij["id"], 900)
        res["jobs"]["image"] = ij
        if check(ij["state"] == "succeeded", f"image: {ij['state']}", ij.get("why") or ""):
            p = ij["outputs"][0]
            check(os.path.getsize(p) > 50_000 and p.startswith(Q.out_root()), f"the PNG: {os.path.getsize(p)} bytes, {p}")
            check((ij.get("note") or {}).get("credits") in (0, None) and "comfyui" in str(ij["note"].get("provider")),
                  f"made on the lab for no credits: {ij.get('note')}")
        res["image_peak_mib"] = (Q.observed().get("image") or {}).get("peak_mib")
        check(res["image_peak_mib"], f"the queue measured the image job's VRAM: {res['image_peak_mib']} MiB")
        log = Q.read_log(ij["id"])
        res["image_log"] = log
        # unload what the image loaded (what the idle-unload sidecar would do in five minutes)
        msg = labmodels.unload("comfyui")
        time.sleep(4)
        after = Q.gpu_view()
        res["gpu_after_unload"] = after
        check(after and after["holds"] < 2048, f"unloaded: {msg}; ComfyUI now holds {after['holds'] if after else '?'} MiB")
    finally:
        svc.terminate()
        svc.wait(30)
    time.sleep(1)
    ns = [json.loads(x) for x in open(notes)] if os.path.exists(notes) else []
    res["notifications"] = ns
    check(any("voice" in n["summary"] and "done" in n["summary"] for n in ns), "a notification for the voice line")
    check(any("image" in n["summary"] and "done" in n["summary"] for n in ns), "a notification for the image")
    nd.terminate()
    res["ok"] = all(c["ok"] for c in res["checks"])
    with open(OUT, "w") as f:
        json.dump(res, f, indent=1, default=str)
    print("e2e:", "PASS" if res["ok"] else "FAIL", OUT)
    sys.exit(0 if res["ok"] else 1)


def wait(jid, timeout):
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        j = Q.get(jid)
        line = (j["state"], j.get("why"), j.get("progress_text"))
        if line != last:
            print(f"  {time.strftime('%H:%M:%S')} {j['id']} {j['state']} {j.get('why') or ''}", flush=True)
            last = line
        if j["state"] in Q.DONE:
            return j
        time.sleep(1)
    Q.cancel(jid)
    return Q.get(jid)


if __name__ == "__main__":
    main()

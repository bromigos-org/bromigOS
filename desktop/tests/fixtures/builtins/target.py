"""bromigos target (stand-in): where AI runs, per service, from fixtures' target.json (each
service's targets with whether they answer); switches keep a service's own order."""
import json

TARGETS = ("homelab", "local", "cloud")


def _doc(st):
    out = []
    for svc, entries in st["services"].items():
        own = (st.get("own") or {}).get(svc)
        order = own or st["order"]
        by = {e[0]: e for e in entries}
        ents = [{"target": t, "ok": by[t][1], "engine": by[t][2], "detail": by[t][3]} for t in order if t in by]
        uses = next(({"target": e["target"], "engine": e["engine"]} for e in ents if e["ok"]), None)
        out.append({"service": svc, "order": order, "own_order": bool(own), "uses": uses, "entries": ents})
    return {"schema": 1, "file": st["file"], "order": st["order"], "yours": bool(st.get("yours")), "services": out}


def run(args, js, F):
    st = F.load("target")
    only = [args[i + 1] for i, a in enumerate(args) if a == "--only" and i + 1 < len(args)]
    words = [a for i, a in enumerate(args) if a != "--only" and (i == 0 or args[i - 1] != "--only")
             and a != "--exclusive"]
    verb = words[0] if words else "show"
    for s in only:
        if s not in st["services"]:
            print(json.dumps({"schema": 1, "ok": False, "error": f"no service {s}"}))
            return 1
    if verb in TARGETS or verb == "order":
        want = words[1:] if verb == "order" else [verb] + [t for t in st["order"] if t != verb]
        if only:
            st.setdefault("own", {})
            for s in only:
                st["own"][s] = want
        else:
            st["order"] = want
        st["yours"] = True
        F.save("target", st)
    elif verb == "reset":
        if only:
            for s in only:
                (st.get("own") or {}).pop(s, None)
        else:
            st["own"] = {}
        st["yours"] = True
        F.save("target", st)
    doc = _doc(st)
    if verb == "probe" and words[1:]:
        doc["services"] = [s for s in doc["services"] if s["service"] in words[1:]]
    print(json.dumps(doc) if js else "\n".join(f"{s['service']}: {(s['uses'] or {}).get('target')}" for s in doc["services"]))

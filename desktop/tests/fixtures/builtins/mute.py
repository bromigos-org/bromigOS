"""bromigos mute (stand-in): the desktop's one mute, kept in fixtures' bromigos.json."""
import json


def run(args, js, F):
    st = F.load("bromigos")
    verb = (args or ["toggle"])[0]
    m = st["mute"]
    if verb in ("on", "off"):
        m["theme"] = m["vector"] = verb == "on"
    elif verb == "toggle":
        on = not (m["theme"] and m["vector"])
        m["theme"] = m["vector"] = on
    F.save("bromigos", st)
    doc = {"schema": 1, "muted": m["theme"] and m["vector"], "theme": m["theme"], "vector": m["vector"]}
    print(json.dumps(doc) if js else ("muted" if doc["muted"] else "unmuted"))

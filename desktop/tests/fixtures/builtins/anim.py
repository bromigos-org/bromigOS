"""bromigos anim (stand-in): the animation switches, kept in fixtures' bromigos.json."""
import json


def run(args, js, F):
    st = F.load("bromigos")
    if len(args) >= 2 and args[0] in ("on", "off", "reset"):
        for n in (list(st["anim"]) if args[1:] == ["all"] else args[1:]):
            st["anim"][n] = args[0] != "off"
        F.save("bromigos", st)
    desc = st.get("anim_desc", {})
    anims = [{"name": n, "on": v, "description": desc.get(n, n), "overridden": False, "keys": []}
             for n, v in st["anim"].items()]
    print(json.dumps({"schema": 1, "animations": anims}) if js else "\n".join(f"{x['name']} {x['on']}" for x in anims))

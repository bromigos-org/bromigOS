"""bromigos peripheral (stand-in): a Razer keyboard's module as `bromigos peripheral list
--json` answered on a machine with one plugged in (fixtures/peripheral.json); enable,
disable and follow change it."""
import json


def run(args, js, F):
    st = F.load("peripheral")
    verb = args[0] if args else "list"
    mods = st["list"]["modules"]

    def mod(i):
        m = next((m for m in mods if m["id"] == i), None)
        if m is None:
            print(json.dumps({"schema": 1, "ok": False, "error": f"no module {i}"}))
            raise SystemExit(1)
        return m
    if verb in ("enable", "disable"):
        m = mod(args[1])
        m["enabled"] = verb == "enable"
        F.save("peripheral", st)
        print(json.dumps({"schema": 1, "ok": True, "detail": f"{m['name']}: {verb}d"}))
        return 0
    if verb == "follow":
        m = mod(args[1])
        m.setdefault("rgb", {})["follow"] = args[2]
        F.save("peripheral", st)
        print(json.dumps({"schema": 1, "ok": True, "detail": f"{m['name']}'s lighting follows {args[2]}"}))
        return 0
    if verb == "refresh":
        print(json.dumps({"schema": 1, "ok": True, "detail": "keys written"}))
        return 0
    doc = st["status"] if verb == "status" else st["list"]
    print(json.dumps(doc) if js else "\n".join(m["id"] for m in mods))
    return 0

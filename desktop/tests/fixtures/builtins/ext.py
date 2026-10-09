"""bromigos ext (stand-in): three extensions installed (a theme, a live deck with an update
waiting, a widget turned off), the catalog as bromigos ext search answered
(fixtures/ext.json); enable, disable, remove and installing a theme change it, installing
code is refused as at a terminal-less run."""
import json


def run(args, js, F):
    st = F.load("ext")
    exts = st["list"]["extensions"]
    verb = args[0] if args else "list"
    rest = [a for a in args[1:] if not a.startswith("--")]

    def out(doc, code=0):
        print(json.dumps(dict({"schema": 1}, **doc)))
        return code

    def find(n):
        return next((e for e in exts if e["name"] == n), None)
    if verb == "list":
        return out({"list": st["list"]})
    if verb == "search":
        return out(st["search"])
    if verb == "update" and "--check" in args:
        ups = [{"name": e["name"], "ok": True, "result": dict(st["updates"].get(e["name"]) or
               {"op": "current", "detail": f"{e['name']} is up to date", "version": e["version"]}, name=e["name"])}
               for e in exts if not rest or e["name"] in rest]
        return out({"updates": ups})
    if verb in ("enable", "disable", "remove"):
        e = find(rest[0]) if rest else None
        if e is None:
            return out({"ok": False, "error": f"{rest[0] if rest else '?'}: not installed"}, 1)
        if verb == "remove":
            exts.remove(e)
        else:
            e["enabled"] = verb == "enable"
            e["status"] = "ok" if e["enabled"] else "disabled"
        F.save("ext", st)
        return out({"result": {"op": verb, "name": e["name"], "detail": f"{verb}d {e['name']}", "next": []}})
    if verb == "install":
        hit = next((r for r in st["search"]["results"] if r["name"] == (rest[0] if rest else "")), None)
        if hit is None:
            return out({"ok": False, "error": "no such extension in the catalogs"}, 1)
        if hit["kinds"] != ["theme"]:
            return out({"ok": False, "error": f"{hit['name']}: not installed (declined)"}, 1)
        hit["installed"] = True
        exts.append({"commit": "1", "enabled": True, "kinds": ["theme"], "name": hit["name"], "source": hit["url"],
                     "status": "ok", "version": "1.0.0"})
        F.save("ext", st)
        return out({"result": {"op": "install", "name": hit["name"], "detail": f"installed {hit['name']} (theme)",
                               "next": [f"bromigos theme set {hit['name']}"]}})
    return out({"ok": False, "error": f"ext {verb} isn't pretended"}, 1)

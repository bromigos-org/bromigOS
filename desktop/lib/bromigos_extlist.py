"""The extensions as the extensions window (`bromigos extensions`, rofi) and Settings ›
Extensions show them: what's installed first, with the catalog's name, words and preview
for it, then the catalogs' extensions that aren't installed. One list, made from
`bromigos ext list --json` and `bromigos ext search --json`; each caller fetches those its
own way (the window waits for them, Settings reads them without blocking) and both show the
same rows with the same actions.

    from bromigos_extlist import merge, fetch, kinds_text
    items, errors = merge(list_doc, search_doc)
    items, errors = fetch(lambda argv, default: …)      # runs the two commands itself
"""
KIND = {"theme": "a theme", "live-deck": "a deck", "live-layer": "a live layer", "widget": "a widget",
        "vector-tool": "a VECTOR tool", "vector-memory": "a VECTOR memory store", "vector-skill": "a VECTOR skill",
        "homelab-adapter": "a homelab adapter", "command": "a command", "hook": "a hook"}

LIST = ["bromigos", "ext", "list", "--json"]
SEARCH = ["bromigos", "ext", "search", "--json"]


def kinds_text(kinds):
    return ", ".join(KIND.get(k, k) for k in kinds or []) or "an extension"


def merge(list_doc, search_doc):
    """(items, catalog errors). Each item: name, title, what, state, installed, enabled, status,
    kinds, version, source, icon (a preview file, if the catalog has one), bundled, theme (a
    theme alone: it installs at once), install (its install command), actions [(label, the
    `bromigos ext` arguments)]."""
    listing = (list_doc or {}).get("list") or {}
    found = search_doc or {}
    catalog = {r["name"]: r for r in found.get("results", [])}
    out = []
    for e in listing.get("extensions", []):
        c = catalog.get(e["name"], {})
        on = e.get("enabled", True)
        out.append({
            "name": e["name"], "title": c.get("display_name") or e["name"],
            "what": c.get("description") or e.get("source", ""),
            "state": f"installed · {e.get('status', 'ok')} · {', '.join(e.get('kinds', []))}",
            "installed": True, "enabled": on, "status": e.get("status", "ok"), "kinds": e.get("kinds", []),
            "version": e.get("version"), "source": e.get("source"), "icon": c.get("preview"), "bundled": False,
            "theme": e.get("kinds") == ["theme"], "install": None,
            "actions": [("Update", ["update", e["name"]]), ("What changed upstream", ["update", e["name"], "--check"]),
                        ("Turn off" if on else "Turn on", ["disable" if on else "enable", e["name"]]),
                        ("Details", ["info", e["name"]]), ("Remove", ["remove", e["name"]])]})
    for r in found.get("results", []):
        if r.get("installed") or any(o["name"] == r["name"] for o in out):
            continue
        out.append({
            "name": r["name"], "title": r.get("display_name") or r["name"], "what": r.get("description", ""),
            "state": "ships with bromigOS" if r.get("bundled") else ", ".join(r.get("kinds", [])),
            "installed": False, "enabled": False, "status": None, "kinds": r.get("kinds", []),
            "version": r.get("version"), "source": r.get("url") or r.get("catalog"), "icon": r.get("preview"),
            "bundled": bool(r.get("bundled")), "theme": r.get("kinds") == ["theme"],
            "install": r.get("install") or ["bromigos", "ext", "install", r["name"]],
            "actions": [] if r.get("bundled") else [("Install", ["install", r["name"]]), ("Details", ["info", r["name"]])]})
    return out, found.get("errors") or []


def fetch(run_json):
    """merge() of the two commands, each run by run_json(argv, default) -> document."""
    return merge(run_json(LIST, {}), run_json(SEARCH, {}))

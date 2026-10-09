"""The lab console's status: cards (`bromigos lab status`, its dashboard, the Lab deck,
Settings › Lab, VECTOR's lab_console). docs/homelab.md, "The lab console".

A card is one part of the lab: nodes, GPUs, services, Argo apps, storage, alerts, the
job queue, and one for every other capability the registry reports. Nothing here names a
vendor: a card is built from a capability's records (caps.collect), so an adapter that
provides a capability shows up on the console by itself, and one that provides a new
capability gets a generic card. Whatever the lab lacks is simply absent; a source that
doesn't answer leaves its card "unreachable", never a crash.

    import bromigos_homelab.console as C
    C.status()              # {"generatedAt", "cards": [card, …], "state", "errors"}
    C.register_card("gpus", title="GPUs", order=20, columns=(…), hint="…")   # shape one

A card (the dict every consumer reads):

    {"id": "gpus", "title": "GPUs", "order": 20,
     "state": "ok" | "warn" | "crit" | "unreachable" | "empty",
     "summary": "4 GPUs · 14.2 of 31.4 GiB used on the RTX 5090",
     "hint": "what the card shows and where it comes from (a hover hint)",
     "columns": ["name", "vram", …],            # the item fields to show, in order
     "items": [{"name": …, "state": "ok"|"warn"|"crit"|"unknown", "hint": "…", …}],
     "errors": {"source": "unreachable: …"}, "sources": ["prometheus", …]}

Ways to add or shape a card (a homelab-adapter extension does the same as bromigOS):
  * provide a capability: its records become a card (a generic one unless shaped);
  * register_card(id, …): title, order, columns, hint, state(rec), summary(items), or a
    whole build(result) -> card;
  * an adapter method cards(self) -> [card, …] for something that isn't a capability.
"""
import concurrent.futures as cf
import importlib
import fnmatch
import time

from . import caps, config, registry

ITEM_STATES = ("ok", "warn", "crit", "unknown")
CARD_STATES = ("ok", "warn", "crit", "unreachable", "empty")
_RANK = {"crit": 3, "unreachable": 3, "warn": 2, "unknown": 1, "ok": 0, "empty": 0}

SPECS = {}      # id -> spec (register_card)

# values a record's state-like field may hold, by what they mean
_CRIT = {"false", "failed", "failure", "error", "down", "degraded", "missing", "crit", "critical", "fail",
         "unreachable", "sealed", "dead", "offline", "notready"}
_WARN = {"pending", "progressing", "out_of_sync", "outofsync", "warn", "warning", "needs_you", "suspended",
         "queued", "waiting", "stale", "standby", "busy"}
_OK = {"true", "running", "healthy", "synced", "ok", "up", "finished", "completed", "success", "online",
       "ready", "done", "idle", "succeeded"}
STATE_FIELDS = ("state", "health", "status", "sync", "up")


def item_state(rec):
    """The generic mapping: the first of state, health, status, sync, up that says something.
    A record with health and sync (an Argo app) takes the worse of the two."""
    seen = []
    for f in STATE_FIELDS:
        if f not in rec or rec[f] is None:
            continue
        v = str(rec[f]).lower().replace(" ", "_").replace("-", "_")
        if v in _CRIT:
            seen.append("crit")
        elif v in _WARN:
            seen.append("warn")
        elif v in _OK:
            seen.append("ok")
    if not seen:
        return "unknown"
    return max(seen, key=lambda s: _RANK[s])


def worst(states):
    states = [s for s in states if s]
    return max(states, key=lambda s: _RANK.get(s, 0)) if states else "ok"


def register_card(id, title=None, order=60, hint="", columns=None, state=None, summary=None, item_hint=None,
                  build=None, capability=None, needs=None, covers=()):
    """Shape a card. id: a capability's name (its records are the items) or a card of its own
    (with build). The first registration of an id wins: a plugin adds cards, never replaces one.

      title      the card's name ("GPUs")
      order      where it sits (bromigOS's: 10 nodes, 20 gpus, 30 services, 40 models,
                 50 deployments, 60 storage, 70 alerts, 80 jobs; others 100+)
      hint       what the card shows and where it comes from
      columns    the record fields to show, in order (default: the capability's schema)
      state      state(rec) -> ok|warn|crit|unknown (default: item_state)
      summary    summary(items) -> one line (default: "N items · M need attention")
      item_hint  item_hint(rec) -> the hover hint for one item
      build      build(result) -> card or None: full control; result is the capability's
                 Result, or None for a card that isn't a capability
      capability the capability to collect (default: id; None with build for no collection)
      needs      the capabilities that must have a provider for the card to show (default: its
                 capability; a build card with none shows always and may return None)
      covers     capabilities this card already shows (no generic card is added for them)
    """
    SPECS.setdefault(id, {"id": id, "title": title or id.replace("_", " ").title(), "order": order, "hint": hint,
                          "columns": list(columns) if columns else None, "state": state, "summary": summary,
                          "item_hint": item_hint, "build": build,
                          "capability": id if capability is None and build is None else capability,
                          "needs": tuple(needs) if needs is not None else None, "covers": tuple(covers)})
    return SPECS[id]


# ------------------------------------------------------------------ settings
def hidden():
    """[console] hide: fnmatch patterns; an item whose name or namespace matches is left off
    every card (e.g. an internal app you don't want on screen)."""
    return [str(p).lower() for p in (config.setting("console", "hide", []) or []) if p]


def _visible(rec, pats):
    if not pats:
        return True
    for f in ("name", "namespace", "model", "repo", "pod"):
        v = rec.get(f)
        if isinstance(v, str) and any(fnmatch.fnmatch(v.lower(), p) for p in pats):
            return False
    return True


# ------------------------------------------------------------------ building cards
def _default_summary(items):
    bad = sum(1 for i in items if i.get("state") in ("warn", "crit"))
    n = len(items)
    return f"{n} {'item' if n == 1 else 'items'}" + (f" · {bad} need attention" if bad else " · all well")


def card_from(spec, result):
    """A card from a spec and a capability Result (or None)."""
    if spec.get("build"):
        c = spec["build"](result)
        if c is None:
            return None
        c = dict(c)
        c.setdefault("id", spec["id"])
        c.setdefault("title", spec["title"])
        c.setdefault("order", spec["order"])
        c.setdefault("hint", spec["hint"])
        return finish(c, result)
    cap = spec.get("capability") or spec["id"]
    pats = hidden()
    items = []
    for r in (result or {}).get("items", []):
        if not _visible(r, pats):
            continue
        it = dict(r)
        try:
            it["state"] = (spec.get("state") or item_state)(r)
        except Exception:
            it["state"] = "unknown"
        if spec.get("item_hint"):
            try:
                it["hint"] = spec["item_hint"](r)
            except Exception:
                pass
        items.append(it)
    cols = spec.get("columns") or list(caps.SCHEMAS.get(cap) or [k for k in (items[0] if items else {})
                                                                  if k not in ("source", "state", "hint")])
    c = {"id": spec["id"], "title": spec["title"], "order": spec["order"], "hint": spec["hint"] or
         f"What the lab's {cap} sources report ({', '.join((result or {}).get('sources') or []) or 'none'})",
         "columns": cols, "items": items}
    try:
        c["summary"] = (spec.get("summary") or _default_summary)(items)
    except Exception:
        c["summary"] = _default_summary(items)
    return finish(c, result)


def finish(c, result=None):
    """Fill the fields every card has, and its state from its items and errors."""
    c.setdefault("items", [])
    c.setdefault("columns", [])
    c.setdefault("summary", "")
    for it in c["items"]:
        it.setdefault("state", item_state(it))
        if it["state"] not in ITEM_STATES:
            it["state"] = "unknown"
    errs = dict(c.get("errors") or {})
    if result:
        errs.update(result.get("errors") or {})
        c.setdefault("sources", list(result.get("sources") or []))
    c["errors"] = errs
    c.setdefault("sources", [])
    if "state" not in c or c["state"] not in CARD_STATES:
        if errs and result is not None and not result.get("ok") and not c["items"]:
            c["state"] = "unreachable"
        elif not c["items"]:
            c["state"] = "empty" if not errs else "unreachable"
        else:
            c["state"] = worst([it["state"] for it in c["items"] if it["state"] != "unknown"] +
                               (["warn"] if errs else []))
    if c["state"] == "unreachable" and not c["summary"]:
        c["summary"] = "unreachable: " + "; ".join(f"{k}: {v}" for k, v in list(errs.items())[:2])
    elif errs and "unreachable" not in c["summary"] and not any(k in c["summary"] for k in errs):
        c["summary"] = (c["summary"] + " · " if c["summary"] else "") + ", ".join(list(errs)[:3]) + " unreachable"
    return c


def unreachable(spec, why):
    return finish({"id": spec["id"], "title": spec["title"], "order": spec["order"], "hint": spec["hint"],
                   "state": "unreachable", "summary": f"unreachable: {why}", "errors": {spec["id"]: why}})


def _wanted(only):
    """The specs to build: bromigOS's and plugins' registered cards whose capability has a
    provider (or that build without one), then a generic card for every other capability
    with a provider."""
    registry.instances()                        # loads plugins (their register_card calls)
    importlib.import_module(__package__ + ".cards")   # bromigOS's own cards register themselves
    out = []
    caps_shown = set()
    for spec in SPECS.values():
        cap = spec.get("capability")
        needs = spec.get("needs")
        if needs is None:
            needs = (cap,) if cap else ()
        if needs and not any(caps.available(n) for n in needs):
            continue
        out.append(spec)
        if cap:
            caps_shown.add(cap)
        caps_shown.update(spec.get("covers") or ())
    for cap in registry.CAPABILITIES:
        if cap in caps_shown or cap == "metrics" or not caps.available(cap):
            continue
        out.append(register_card(cap, order=100))
    if only:
        out = [s for s in out if s["id"] in only]
    return out


def _adapter_cards():
    out = []
    for a in registry.instances():
        fn = getattr(a, "cards", None)
        if not callable(fn):
            continue
        try:
            for c in fn() or []:
                c = dict(c)
                c.setdefault("id", f"{a.name}.{c.get('title', 'card')}".lower().replace(" ", "-"))
                c.setdefault("title", a.name)
                c.setdefault("order", 150)
                c.setdefault("hint", f"From {a.name} ({a.type})")
                c.setdefault("sources", [a.name])
                out.append(finish(c))
        except Exception as e:
            out.append(finish({"id": f"{a.name}.cards", "title": a.name.upper(), "order": 150,
                               "hint": f"Cards from {a.name} ({a.type})", "state": "unreachable",
                               "summary": caps._why(e), "errors": {a.name: caps._why(e)}}))
    return out


def status(only=None, timeout=20):
    """Every card the lab has: {"generatedAt", "state", "cards", "errors", "configured"}.
    only: a set of card ids. Cards are built in parallel; one that takes longer than
    timeout seconds reads unreachable (timed out)."""
    t0 = time.time()
    if not registry.instances():
        return {"generatedAt": int(t0), "configured": False, "state": "empty", "cards": [], "errors": {},
                "configured_hint": "no sources: bromigos lab connect (or bromigos setup homelab)"}
    specs = _wanted(set(only) if only else None)
    cards = []
    ex = cf.ThreadPoolExecutor(min(12, max(1, len(specs) + 1)))
    try:
        def one(spec):
            res = caps.collect(spec["capability"]) if spec.get("capability") else None
            return card_from(spec, res)
        futs = {ex.submit(one, s): s for s in specs}
        extra = ex.submit(_adapter_cards) if not only else None
        for f, spec in futs.items():
            try:
                c = f.result(timeout=max(1.0, timeout - (time.time() - t0)))
            except cf.TimeoutError:
                c = unreachable(spec, f"timed out after {timeout} s")
            except Exception as e:
                c = unreachable(spec, caps._why(e))
            if c is not None:
                cards.append(c)
        if extra is not None:
            try:
                cards += extra.result(timeout=max(1.0, timeout - (time.time() - t0)))
            except Exception:
                pass
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    cards.sort(key=lambda c: (c.get("order", 100), c.get("title", "")))
    errs = {}
    for c in cards:
        errs.update(c.get("errors") or {})
    return {"generatedAt": int(t0), "configured": True, "seconds": round(time.time() - t0, 2),
            "state": worst([c["state"] for c in cards if c["state"] != "empty"]), "cards": cards,
            "errors": errs}


def card(status_doc, card_id):
    return next((c for c in status_doc.get("cards", []) if c.get("id") == card_id), None)

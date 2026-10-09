"""Model upgrades: what the lab's opt-in upgrade policy would do now, and the weekly nudge
(docs/lab-models.md, "Upgrades").

The policy is ~/.config/bromigos/lab.toml's [upgrade] (or homelab.toml's [lab.upgrade]), per
capability, every one off by default:

    [upgrade]
    enabled = false                 # the global switch
    action = "notify"               # notify (tell me) | apply (Phase 2: through the homelab repo)
    quiet_hours = "01:00-06:00"     # when an upgrade may apply (local time)
    policy = { image = "safe", video = "any" }    # off | safe | any

- **safe**: only a newer version, or a better quantisation, of the same model family, within
  the GPU's budget and the goal.
- **any**: any catalog pick that beats the current one for that capability, within the
  budget, the goal and the licence filter.

Nothing here changes the lab. `bromigos lab models upgrades` shows the proposals; applying
them is Phase 2's `lab models replace` (a pull request to the homelab repo, deployed beside
the old model, smoke-tested, switched, the old one kept N days; docs/lab-models.md).
The nudge (`upgrades --nudge`, bromigos-lab-models.timer, weekly) says once, quietly, when a
better model fits a GPU, whatever the policy; it never installs anything.
"""
import datetime
import json
import os
import sys

from . import catalog as C

POLICIES = ("off", "safe", "any")
ACTIONS = ("notify", "apply")
MIN_GAIN = 3.0                     # quality points that count as better (the scores' noise is ~2)
STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "bromigos", "lab")


def settings(table=None):
    """[lab.upgrade], defaults filled in."""
    if table is None:
        table = dict(C.read_settings().get("upgrade") or {})
    pol = {C.canon(k): str(v) for k, v in (table.get("policy") or {}).items()}
    for k, v in pol.items():
        if v not in POLICIES:
            raise C.CatalogError(f"[lab.upgrade] policy {k} = {v!r}: off, safe or any")
    act = table.get("action", "notify")
    if act not in ACTIONS:
        raise C.CatalogError(f"[lab.upgrade] action = {act!r}: notify or apply")
    return {"enabled": bool(table.get("enabled", False)), "action": act,
            "quiet_hours": table.get("quiet_hours", "01:00-06:00"), "policy": pol}


def in_quiet_hours(window, now=None):
    """Whether `now` (local) is inside "HH:MM-HH:MM" (it may wrap midnight)."""
    try:
        a, b = [datetime.time.fromisoformat(x.strip()) for x in window.split("-")]
    except (ValueError, AttributeError):
        return False
    t = (now or datetime.datetime.now()).time()
    return a <= t < b if a <= b else (t >= a or t < b)


def _current(cat, have, cap):
    """The best installed variant for a capability on a device: (Variant, quality) or (None, None)."""
    best = None
    for h in have:
        if cap not in h["caps"]:
            continue
        v = cat.variant(h["key"])
        if v and (best is None or v.quality(cap) > best[1]):
            best = (v, v.quality(cap))
    return best or (None, None)


def _room(cat, d, have, cap, cur):
    """GiB the new model may take on this device: its budget, less the other always-on models
    installed there (an on-demand model swaps with the other on-demand ones)."""
    others = 0.0
    for h in have:
        v = cat.variant(h["key"])
        if not v or v is cur or cap in h["caps"]:
            continue
        if any(cat.caps[c].residency == "always" for c in h["caps"]):
            others += v.vram_gib
    return d.give() - others - C._headroom(d)


def kind_of(cur, new):
    """safe's two cases, or None when it's a different model family."""
    if new.model.id == cur.model.id:
        return "better quantisation" if new.id != cur.id else None
    if cur.model.family and new.model.family == cur.model.family:
        if (new.model.released or "") > (cur.model.released or ""):
            return "newer version"
    return None


def evaluate(cat=None, hw=None, have=None, policy=None, goal="balanced", licence="any", region=None,
             budgets=None, now=None, nudge=False):
    """{"enabled", "action", "quiet_hours", "in_quiet_hours", "proposals": [...], "held": [...]}.

    hw: Hardware (detect()); have: catalog.installed() rows ({key, where, caps, …}) matched to
    devices by catalog._held_on; policy: settings() (or a [lab.upgrade]-shaped dict). With
    nudge, every capability is looked at as "any" whatever the policy (the weekly nudge tells,
    never applies)."""
    cat = cat or C.load()
    pol = settings(policy)
    if hw is None or have is None:
        from . import labmodels
        inv = labmodels.inventory()
        inv["served"] = C.served_models()
        hw = hw or C.detect(cat, inv)
        have = C.installed(cat, inv) if have is None else have
    hw.apply_budgets(budgets)
    out = {"enabled": pol["enabled"], "action": pol["action"], "quiet_hours": pol["quiet_hours"],
           "in_quiet_hours": in_quiet_hours(pol["quiet_hours"], now), "goal": goal, "licence": licence,
           "proposals": [], "held": []}
    for d in hw.devices:
        if d.vendor == "cpu":
            continue
        here = [h for h in have if C._held_on(h, d)]
        caps = sorted({c for h in here for c in h["caps"]}, key=lambda c: C.CAPABILITIES.index(c))
        for cap in caps:
            p = "any" if nudge else pol["policy"].get(cap, "off")
            if p == "off":
                continue
            cur, cur_q = _current(cat, here, cap)
            if cur is None:
                continue
            room = _room(cat, d, here, cap, cur)
            sub = C.Hardware([d], hw.ram_gib)
            opts = C.options(cat, cap, sub, licence, region)
            cur_u = None
            for o in opts:
                if o.variant is cur:
                    cur_u = C.utility(o, goal)
            best = None
            for o in sorted(opts, key=lambda o: -C.utility(o, goal)):
                if o.variant is cur or o.variant.model.id == cur.model.id and o.variant.id == cur.id:
                    continue
                if o.per_gpu > room:
                    continue
                gain = o.quality - cur_q
                if gain < MIN_GAIN and not (p == "safe" and kind_of(cur, o.variant) == "better quantisation"
                                            and gain > 0):
                    continue
                if cur_u is not None and C.utility(o, goal) <= cur_u:
                    continue
                k = kind_of(cur, o.variant)
                if p == "safe" and not k:
                    continue
                best = (o, k or "better model", gain)
                break
            if not best:
                continue
            o, k, gain = best
            v = o.variant
            lic_changed = v.model.licence.id != cur.model.licence.id
            row = {"device": d.key, "device_id": d.id, "capability": cap, "policy": p, "kind": k,
                   "from": f"{cur.model.name} {cur.quant}", "from_key": cur.key,
                   "to": f"{v.model.name} {v.quant}", "to_key": v.key, "gain": round(gain, 1),
                   "vram_gib": o.per_gpu, "vram_delta_gib": round(o.per_gpu - cur.vram_gib, 1),
                   "speed_text": C.fmt_speed(cat, cap, o.speed), "licence": v.model.licence.name,
                   "licence_plain": v.model.licence.plain(), "licence_changed": lic_changed,
                   "runtime": v.runtime, "workflow": v.workflow, "stack": v.stack,
                   "voice": cap in ("tts", "stt")}
            row["reason"] = (f"{row['to']} is {k if k != 'better model' else 'a stronger model'} for {cap} "
                             f"(+{gain:.0f} quality, {o.per_gpu:.1f} GiB of {d.give():.0f} on the {d.name})"
                             + (f"; its licence is {v.model.licence.name}: {v.model.licence.plain()}"
                                if lic_changed else ""))
            if nudge:
                row["action"] = "tell"
            elif not pol["enabled"]:
                row["action"] = "none (upgrades are switched off)"
            elif pol["action"] == "notify":
                row["action"] = "notify"
            else:
                row["action"] = "apply (Phase 2: lab models replace)" + (
                    "" if out["in_quiet_hours"] else f", in quiet hours {pol['quiet_hours']}")
            if row["voice"]:
                row["reason"] += "; the voice service changes only while VECTOR is quiet"
            out["proposals"].append(row)
    return out


# ------------------------------------------------------------------ the weekly nudge
def nudge(cat=None, ev=None, state_file=None, notify=None):
    """One quiet notification for what's new since the last nudge (each suggestion once)."""
    state_file = state_file or os.path.join(STATE, "nudged.json")
    try:
        with open(state_file) as f:
            told = json.load(f)
    except (OSError, ValueError):
        told = {}
    ev = ev or evaluate(cat, nudge=True, **_plan_settings())
    new = [p for p in ev["proposals"] if told.get(f"{p['device']}|{p['capability']}") != p["to_key"]]
    if not new:
        return None
    best = max(new, key=lambda p: p["gain"])
    body = (f"A better {best['capability']} model fits your {best['device']}: {best['to']} (+{best['gain']:.0f} "
            f"quality, {best['vram_gib']:.0f} GiB). See bromigos lab models plan.")
    if len(new) > 1:
        body += f" ({len(new) - 1} more: bromigos lab models upgrades)"
    if notify is None:
        from .jobqueue import notify as _n
        notify = _n
    notify("Lab models", body, "low", "applications-science")
    for p in new:
        told[f"{p['device']}|{p['capability']}"] = p["to_key"]
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    tmp = state_file + ".tmp"
    with open(tmp, "w") as f:
        json.dump(told, f, indent=1)
    os.replace(tmp, state_file)
    return body


def _plan_settings():
    s = C.settings()
    return {"goal": s["goal"], "licence": s["licence"], "region": s["region"], "budgets": s["budgets"]}


def main(argv):
    js = "--json" in argv
    try:
        if "--nudge" in argv:
            from . import config
            if not config.sources():
                return 0                                      # no lab: nothing to say
            said = nudge()
            if js:
                print(json.dumps({"told": said}))
            elif said:
                print(said)
            return 0
        if "--apply" in argv:
            print("Applying an upgrade lands with Phase 2 (bromigos lab models replace): a pull request to "
                  "your homelab repo, deployed beside the old model, smoke-tested, then switched. Nothing was "
                  "changed. What the policy would do now:", file=sys.stderr)
        ev = evaluate(**_plan_settings())
    except C.CatalogError as e:
        print(f"bromigos lab models upgrades: {e}", file=sys.stderr)
        return 2
    if js:
        print(json.dumps(ev, indent=1))
        return 3 if "--apply" in argv else 0
    print(f"upgrades: {'on' if ev['enabled'] else 'off'} · action: {ev['action']} · quiet hours "
          f"{ev['quiet_hours']}{' (now)' if ev['in_quiet_hours'] else ''} · goal {ev['goal']} · licence {ev['licence']}")
    if not ev["proposals"]:
        print("nothing to upgrade under the policy (bromigos lab models recommend shows every better fit)")
    for p in ev["proposals"]:
        print(f"  {p['device']} {p['capability']:<10} [{p['policy']}] {p['from']} -> {p['to']}: {p['reason']} "
              f"· {p['action']}")
    return 3 if "--apply" in argv else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

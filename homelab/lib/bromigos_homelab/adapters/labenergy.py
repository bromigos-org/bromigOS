"""Home energy: Enphase's IQ Gateway (the Envoy). Capability: energy. Read-only.

    [[source]]
    type = "enphase"
    endpoint = "https://envoy.local"          # the gateway on your network
    auth_ref = "@file:~/.config/bromigos/envoy.token"   # firmware 7 and later: an owner token
    tls_verify = false                        # its certificate is self-signed (or set tls_ca)
    # history_metric = "envoy_production_watts"   # optional: the day's curve from your metrics source

Firmware 7 and later answer only over HTTPS, with a token (a JWT an owner gets once a
year from entrez.enphaseenergy.com), sent as a bearer header. Older firmware answers
over plain HTTP with no token. Both serve GET /production.json?details=1: what the
inverters make, and, when the gateway has current transformers (CTs), the metered
production and what the house uses ("eim"). Without production.json, /api/v1/production
gives the inverters' totals.

Each record: production_w (now), consumption_w (what the house uses), net_w (from the
grid: positive imports, negative exports), today_wh, consumed_today_wh, lifetime_wh,
battery_pct and battery_w (when there are batteries), inverters (reporting).
"""
from ..registry import Adapter, Unreachable, register
from . import labcommon as L


def _active(rows, type_=None, measure=None):
    """The first row of a production.json list with that type / measurementType that reports."""
    for r in rows or []:
        if type_ and r.get("type") != type_:
            continue
        if measure and r.get("measurementType") != measure:
            continue
        if r.get("activeCount", 1) in (0, None) and type_ == "eim":
            continue
        return r
    return None


def energy_from_production(d, name="enphase"):
    """An energy record from /production.json (any firmware), or None when it has nothing."""
    if not isinstance(d, dict):
        return None
    prod = d.get("production") or []
    inv = _active(prod, "inverters")
    eim = _active(prod, "eim", "production")
    total = _active(d.get("consumption"), "eim", "total-consumption")
    net = _active(d.get("consumption"), "eim", "net-consumption")
    bat = next((r for r in d.get("storage") or [] if r.get("activeCount")), None)
    if not (inv or eim):
        return None
    p_now = (eim or inv).get("wNow")
    c_now = total.get("wNow") if total else None
    n_now = net.get("wNow") if net else None
    if c_now is None and n_now is not None and p_now is not None:
        c_now = p_now + n_now
    if n_now is None and c_now is not None and p_now is not None:
        n_now = c_now - p_now
    rec = {"name": name, "kind": "solar", "production_w": _num(p_now), "consumption_w": _num(c_now), "net_w": _num(n_now),
           "today_wh": _num((eim or {}).get("whToday")) if eim else None,
           "consumed_today_wh": _num(total.get("whToday")) if total else None,
           "lifetime_wh": _num((eim or inv).get("whLifetime")),
           "battery_pct": _num(bat.get("percentFull")) if bat else None,
           "battery_w": _num(bat.get("wNow")) if bat else None,
           "inverters": inv.get("activeCount") if inv else None,
           "metered": bool(eim or total), "read_at": (eim or inv).get("readingTime")}
    rec["state"] = "ok" if rec["production_w"] is not None else "unknown"
    return rec


def energy_from_v1(d, name="enphase"):
    """An energy record from /api/v1/production (the inverters' totals, no consumption)."""
    if not isinstance(d, dict) or "wattsNow" not in d:
        return None
    return {"name": name, "kind": "solar", "production_w": _num(d.get("wattsNow")), "consumption_w": None, "net_w": None,
            "today_wh": _num(d.get("wattHoursToday")), "consumed_today_wh": None,
            "lifetime_wh": _num(d.get("wattHoursLifetime")), "battery_pct": None, "battery_w": None, "inverters": None,
            "metered": False, "read_at": None, "state": "ok"}


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


@register
class Enphase(Adapter):
    type = "enphase"
    provides = ("energy",)
    default_scheme = "https"

    def probe(self):
        try:
            b = self.request("/info.xml", timeout=3, raw=True)
        except Exception:                                     # noqa: BLE001  not one
            return False
        return b"<envoy_info" in b or b"Envoy" in b

    def energy(self):
        if not self.endpoint:
            raise Unreachable(f"{self.name}: no endpoint (the gateway's address) in homelab.toml")
        try:
            rec = energy_from_production(self.get_json("/production.json?details=1", timeout=8), self.name)
        except Unreachable:
            raise
        except Exception as e:                                # noqa: BLE001  401 (no token), 404 (old firmware)
            if getattr(e, "code", None) == 401:
                raise Unreachable(f"{self.name}: the gateway wants a token (firmware 7 or later): set auth_ref") from None
            rec = None
        if rec is None:
            rec = energy_from_v1(self.get_json("/api/v1/production", timeout=8), self.name)
        if rec is None:
            raise Unreachable(f"{self.name}: the gateway answered, but with no production readings")
        hm = self.opts.get("history_metric")
        if hm:
            rec["history_metric"] = hm
        return [rec]

    def doctor(self):
        try:
            recs = self.energy()
        except Exception as e:                                # noqa: BLE001
            return [L.finding(f"energy.{self.name}", f"Solar ({self.name})", "fail", str(e)[:160],
                              "Check the gateway's address, and for firmware 7 or later an owner token in auth_ref "
                              "(entrez.enphaseenergy.com).", self.name)]
        r = recs[0]
        detail = f"making {r['production_w'] or 0:.0f} W"
        if r.get("consumption_w") is not None:
            detail += f", the house uses {r['consumption_w']:.0f} W"
        return [L.finding(f"energy.{self.name}", f"Solar ({self.name})", "ok", detail, source=self.name)]

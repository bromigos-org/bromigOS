"""The homelab integrations, when bromigos-homelab is installed (docs/homelab.md).

    from .homelab import H     # the bromigos_homelab module, or None without the package
    if H and H.available("metrics"): …

Everything that reads the lab goes through here, so without the package the live layer
simply has no lab: no errors, no empty panels, the worlds' homelab signals at rest.
"""
try:
    import bromigos_homelab as H
except ImportError:
    H = None


def lab_name():
    """What the views call the lab: homelab.toml's `name`, upper case ("LAB" without one)."""
    try:
        return (H.lab_name() if H and hasattr(H, "lab_name") else "LAB").upper()
    except Exception:
        return "LAB"


def constellation():
    """homelab.toml's [constellation] (hub, ai, positions; references resolved), {} without."""
    try:
        return H.config.table("constellation") if H else {}
    except Exception:
        return {}


def has(capability):
    """Does anything in homelab.toml provide that capability (and is the package installed)?"""
    return bool(H) and H.available(capability)

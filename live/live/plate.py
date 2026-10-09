"""The clean plate: the den wallpaper with its baked decorative motion removed,
so the live layer can redraw that motion as seamless loops without doubling it.

The wallpaper file is never modified; this works on an in-memory copy.

  * steam      the baked wisps above the mug are replaced by the v1 plate (which
               has none) through a soft mask taken from the steam itself
               (variant - v1, blurred), so only steam pixels change;
  * streaks    the baked horizontal glitch streaks on the left are inpainted
               (vertical interpolation across each streak) and returned as
               segments for the shader to redraw, drifting;
  * floor rows the baked horizontal grid rows are inpainted the same way; the
               shader redraws them scrolling (the converging columns stay baked:
               a forward scroll leaves them where they are).

All coordinates are in the 2560x1440 plate; callers scale.
"""
import os

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view as _sw

PLATE_W, PLATE_H = 2560, 1440
STEAM_BOX = (1220, 1000, 1480, 1262)            # x0, y0, x1, y1
LEFT_X1 = 1100                                  # streak/row analysis region: x < this
HORIZON = 929                                   # floor rows below, sky streaks above
FLOOR_X1 = 992                                  # the rack starts here at floor level
# Baked floor rows (y at x≈250-850), nearest first, measured from the v1 plate;
# extended one row past the bottom edge and two toward the horizon.
ROWS = [1570.0, 1476.0, 1390.0, 1314.0, 1246.0, 1188.0, 1139.0, 1099.0, 1063.0, 1030.0,
        1006.0, 984.0, 970.0, 958.0, 945.0, 933.0, 929.5, 927.6]


def _vmin(a, k):
    p = np.pad(a, ((k // 2, k // 2), (0, 0)), mode="edge")
    return _sw(p, k, axis=0).min(axis=-1)


def _vmax(a, k):
    p = np.pad(a, ((k // 2, k // 2), (0, 0)), mode="edge")
    return _sw(p, k, axis=0).max(axis=-1)


def _hrun(mask, n):
    """Keep only pixels that belong to a horizontal run of at least n."""
    p = np.pad(mask, ((0, 0), (n // 2, n - 1 - n // 2)))
    core = _sw(p, n, axis=1).all(axis=-1)
    p = np.pad(core, ((0, 0), (n - 1 - n // 2, n // 2)))
    return _sw(p, n, axis=1).any(axis=-1)


def _vdilate(mask, r):
    p = np.pad(mask, ((r, r), (0, 0)))
    return _sw(p, 2 * r + 1, axis=0).any(axis=-1)


def _box_blur(a, r):
    k = 2 * r + 1
    p = np.pad(a, r, mode="edge")
    c = p.cumsum(0).cumsum(1)
    c = np.pad(c, ((1, 0), (1, 0)))
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


def _inpaint_vertical(img, mask):
    """Replace masked pixels by linear interpolation between the nearest
    unmasked pixels above and below in the same column."""
    h, w = mask.shape
    rows = np.arange(h)[:, None].repeat(w, 1)
    above = np.where(~mask, rows, -1)
    above = np.maximum.accumulate(above, axis=0)
    below = np.where(~mask, rows, h)
    below = np.minimum.accumulate(below[::-1], axis=0)[::-1]
    ys, xs = np.nonzero(mask)
    a, b = above[ys, xs], below[ys, xs]
    a_ok, b_ok = a >= 0, b < h
    a_c, b_c = np.clip(a, 0, h - 1), np.clip(b, 0, h - 1)
    va, vb = img[a_c, xs], img[b_c, xs]
    t = np.where(a_ok & b_ok, (ys - a) / np.maximum(b - a, 1), 0.5)[:, None]
    va = np.where(a_ok[:, None], va, vb)
    vb = np.where(b_ok[:, None], vb, va)
    out = img.copy()
    out[ys, xs] = va * (1 - t) + vb * t
    return out


def _clone(img, mask, d):
    """Fill masked pixels with the texture d rows above (or below when that is
    masked too): keeps the plate's fine scanline grain, unlike interpolation."""
    h = mask.shape[0]
    ys, xs = np.nonzero(mask)
    up = np.clip(ys - d, 0, h - 1)
    dn = np.clip(ys + d, 0, h - 1)
    use_up = ~mask[up, xs] & (ys - d >= 0)
    src = np.where(use_up, up, dn)
    out = img.copy()
    out[ys, xs] = img[src, xs]
    return out


def _segments(mask, res, img):
    """Group the streak mask into horizontal segments for the shader."""
    segs = []
    ys = np.nonzero(mask.any(axis=1))[0]
    for y in ys:
        xs = np.nonzero(mask[y])[0]
        br = np.nonzero(np.diff(xs) > 24)[0]
        for a, b in zip(np.r_[0, br + 1], np.r_[br, len(xs) - 1]):
            segs.append([int(y), int(y), int(xs[a]), int(xs[b])])
    boxes = []
    for y, _, x0, x1 in segs:
        for bx in boxes:
            if y - bx[1] <= 3 and x0 <= bx[3] + 24 and x1 >= bx[2] - 24:
                bx[1] = y
                bx[2], bx[3] = min(bx[2], x0), max(bx[3], x1)
                break
        else:
            boxes.append([y, y, x0, x1])
    out = []
    for y0, y1, x0, x1 in boxes:
        if x1 - x0 < 20:
            continue
        # grow along the row while the streak continues (gaps up to 10 px)
        prof = res[max(y0 - 1, 0):y1 + 2].max(axis=0)
        thr = max(12.0, 0.3 * float(res[y0:y1 + 1, x0:x1 + 1].max()))
        gap = 0
        while x0 > 0 and gap <= 10:
            x0 -= 1
            gap = 0 if prof[x0] > thr else gap + 1
        x0 += gap
        gap = 0
        while x1 < len(prof) - 1 and gap <= 10:
            x1 += 1
            gap = 0 if prof[x1] > thr else gap + 1
        x1 -= gap
        if x0 <= 3:
            x0 = 0
        blk = res[y0:y1 + 1, x0:x1 + 1]
        amp = float(blk.max())
        if amp < 40:
            continue
        # the core row: the brightest one
        yc = y0 + int(np.argmax(blk.max(axis=1)))
        out.append({"x0": x0, "x1": x1, "y": yc, "thick": max(1.0, (y1 - y0 + 1) * 0.45),
                    "amp": min(amp / 255.0, 0.75)})
    out.sort(key=lambda s: -s["amp"] * (s["x1"] - s["x0"]))
    return out[:16]


def build(variant, v1=None, steam=True, streaks=True, rows=True):
    """variant, v1: float32 arrays (1440, 2560, 3) in 0..255. Returns
    (clean uint8 array, streak segments, info dict)."""
    img = variant.astype(np.float32)
    info = {"steam_masked": 0.0}
    if steam and v1 is not None:
        x0, y0, x1, y1 = STEAM_BOX
        d = (img[y0:y1, x0:x1] - v1[y0:y1, x0:x1]).mean(axis=2)
        m = _box_blur(np.clip(d, 0, None), 6)
        m = np.clip((m - 3.0) / 10.0, 0.0, 1.0)
        m = m * m * (3 - 2 * m)
        info["steam_masked"] = float(m.mean())
        img[y0:y1, x0:x1] = img[y0:y1, x0:x1] * (1 - m[..., None]) + v1[y0:y1, x0:x1] * m[..., None]
    segs = []
    if streaks or rows:
        L = img[:, :LEFT_X1]
        lum = L.mean(axis=2)
        res = lum - _vmax(_vmin(lum, 7), 7)
        yy = np.arange(PLATE_H)[:, None]
        xx = np.arange(LEFT_X1)[None, :]
        if rows:
            rmask = _hrun(res > 5, 12) & (yy >= HORIZON) & (xx < FLOOR_X1)
            rmask = _vdilate(rmask, 1) & (yy >= HORIZON - 1)
            L = _clone(L, rmask, 4)
            info["row_px"] = int(rmask.sum())
        if streaks:
            edge = (xx < 220) | (xx >= FLOOR_X1)
            bright = _hrun(res > 10, 10) & ((yy < HORIZON) | (_hrun(res > 55, 4) & edge))
            segs = _segments(bright, res, L)
            smask = np.zeros_like(bright)
            for sg in segs:   # the whole box, halo included
                t = int(np.ceil(sg["thick"])) + 4
                smask[max(sg["y"] - t, 0):sg["y"] + t + 1, max(sg["x0"] - 8, 0):sg["x1"] + 9] = True
            L = _clone(L, smask, 18)
            info["streak_px"] = int(smask.sum())
        img[:, :LEFT_X1] = L
    return np.clip(img + 0.5, 0, 255).astype(np.uint8), segs, info


def load_rgb(path):
    from . import pixbuf                         # rows at their own stride; alpha over black
    return pixbuf.load(path, PLATE_W, PLATE_H)[0].astype(np.float32)


_CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "bromigos-live")


def clean_plate(path, v1_path, **kw):
    """Cached by (file sha1, v1 sha1, options): building takes ~1 s, loading ~50 ms."""
    import hashlib
    import json
    def sha(p):
        with open(p, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    key = sha(path) + "-" + (sha(v1_path) if v1_path and os.path.exists(v1_path) else "none") + "-" + \
        "".join("1" if kw.get(k, True) else "0" for k in ("steam", "streaks", "rows")) + "-v6"
    npz = os.path.join(_CACHE, f"plate-{key}.npz")
    try:
        z = np.load(npz, allow_pickle=False)
        return z["img"], json.loads(str(z["segs"])), json.loads(str(z["info"]))
    except (OSError, KeyError, ValueError):
        pass
    var = load_rgb(path)
    v1 = load_rgb(v1_path) if v1_path and os.path.exists(v1_path) else None
    img, segs, info = build(var, v1, **kw)
    try:
        os.makedirs(_CACHE, exist_ok=True)
        for old in os.listdir(_CACHE):
            if old.startswith("plate-") and old != os.path.basename(npz):
                os.remove(os.path.join(_CACHE, old))
        np.savez(npz, img=img, segs=json.dumps(segs), info=json.dumps(info))
    except OSError:
        pass
    return img, segs, info

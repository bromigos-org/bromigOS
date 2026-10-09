"""A GdkPixbuf's pixels as a numpy array, and back, for any width.

A GdkPixbuf keeps its rows `rowstride` bytes apart, each padded to a multiple of 4,
except the last row, which isn't padded at all: the buffer is
`(h - 1) * rowstride + w * n_channels` bytes. When `w * n_channels` isn't a multiple of
4 (a 1366-wide screen, or 1422: a 1280x800 screen's 16:9 cover) that buffer can't be
reshaped to `(h, rowstride)`, and reading it as `w * 3` bytes a row shears the picture.
`rgb()` reads every row at its own stride; three channels or four (alpha dropped).
"""
import numpy as np


def rgb(pb):
    """The pixbuf's pixels, (h, w, 3) uint8, contiguous."""
    w, h, n = pb.get_width(), pb.get_height(), pb.get_n_channels()
    stride = pb.get_rowstride()
    if pb.get_bits_per_sample() != 8 or n not in (3, 4):
        raise ValueError(f"pixbuf: {pb.get_bits_per_sample()}-bit, {n} channels (8-bit RGB or RGBA expected)")
    data = pb.read_pixel_bytes().get_data()
    buf = np.frombuffer(data, dtype=np.uint8)
    need = (h - 1) * stride + w * n if h else 0
    if buf.size < need or stride < w * n:
        raise ValueError(f"pixbuf: {buf.size} bytes for {w}x{h}x{n} at a stride of {stride} (needs {need})")
    rows = np.lib.stride_tricks.as_strided(buf, shape=(h, w * n), strides=(stride, 1), writeable=False)
    return np.ascontiguousarray(rows.reshape(h, w, n)[..., :3])


def from_rgb(img):
    """A pixbuf holding an (h, w, 3) uint8 array (rows padded to 4 bytes, as GdkPixbuf's own)."""
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf, GLib
    img = np.asarray(img, dtype=np.uint8)
    h, w = img.shape[:2]
    stride = (w * 3 + 3) & ~3
    padded = np.zeros((h, stride), np.uint8)
    padded[:, :w * 3] = img.reshape(h, w * 3)
    return GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(padded.tobytes()), GdkPixbuf.Colorspace.RGB,
                                           False, 8, w, h, stride)


def load(path, w, h):
    """An image file at w x h (stretched: callers cover-fit), (h, w, 3) uint8; transparency
    over black. Also returns the pixbuf."""
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, w, h, False)
    if pb.get_has_alpha():
        pb = pb.composite_color_simple(w, h, GdkPixbuf.InterpType.BILINEAR, 255, 1, 0, 0)
    return rgb(pb), pb


def scale(img, w, h):
    """An (h0, w0, 3) uint8 array scaled to w x h (bilinear, GdkPixbuf's)."""
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    return rgb(from_rgb(img).scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR))

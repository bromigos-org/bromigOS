"""A stand-in art folder for STATIC: solid-colour PNG frames and a manifest, made here (no
image library), so the tests can see rendered art replace the placeholder."""
import json
import os
import struct
import zlib


def png(w, h, rgba):
    raw = b"".join(b"\0" + bytes(rgba) * w for _ in range(h))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


MAGENTA = (255, 0, 255, 255)


def folder(path, names=("snow", "asleep", "host", "antenna", "whack", "watching", "head:watching", "remote:snow"),
           heights=(64, 256), frames=2, colour=MAGENTA):
    os.makedirs(path, exist_ok=True)
    art = {}
    for name in names:
        safe = name.replace(":", "-")
        art[name] = {}
        for h in heights:
            files = []
            for n in range(frames):
                f = f"{safe}-{h}-{n:02d}.png"
                with open(os.path.join(path, f), "wb") as fh:
                    fh.write(png(max(1, h * 2 // 3), h, colour))
                files.append(f)
            art[name][str(h)] = files
    with open(os.path.join(path, "manifest.json"), "w") as f:
        json.dump({"schema": 1, "fps": 6, "art": art}, f)
    return path

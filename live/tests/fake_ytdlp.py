#!/usr/bin/env python3
"""A stand-in for yt-dlp in the tests (BROMIGOS_YTDLP points at it): no network, ever.

  --flat-playlist -J URL      prints a recorded listing from tests/fixtures (ytdlp-*.json):
                              a channel's /streams tab, its /videos tab (or any other
                              channel URL), a playlist; a URL with "gone" fails as a removed
                              video does, "slow" never answers in time
  a download (--print after_move:filepath)
                              writes a small file where the -o template says, with the info
                              JSON and the thumbnail beside it, and prints its path; a URL
                              with "agegate" fails as an age-gated video does

Every call is appended to $FAKE_YTDLP_LOG, one JSON list per line.
"""
import json
import os
import re
import sys
import time

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
args = sys.argv[1:]
if os.environ.get("FAKE_YTDLP_LOG"):
    with open(os.environ["FAKE_YTDLP_LOG"], "a") as f:
        f.write(json.dumps(args) + "\n")
url = args[-1]

if "--flat-playlist" in args:
    if "gone" in url:
        print("ERROR: [youtube:tab] gone: This channel does not exist.", file=sys.stderr)
        sys.exit(1)
    if "slow" in url:
        time.sleep(30)
    name = ("ytdlp-streams.json" if url.endswith("/streams") else "ytdlp-playlist.json" if "list=" in url
            else "ytdlp-videos.json" if url.endswith("/videos") else "ytdlp-channel.json")
    with open(os.path.join(FIX, name)) as f:
        print(f.read())
    sys.exit(0)

if "--print" in args:
    if "agegate" in url:
        print("ERROR: [youtube] agegate: Sign in to confirm your age. This video may be inappropriate for some users.",
              file=sys.stderr)
        sys.exit(1)
    vid = url.rsplit("=", 1)[-1].rsplit("/", 1)[-1]
    info = {"id": vid, "title": f"Video {vid}", "channel": "Example Studio", "upload_date": "20260314",
            "description": "A test video & <its> notes."}
    outs = [args[i + 1] for i, a in enumerate(args) if a == "-o"]
    main = next(o for o in outs if not re.match(r"^\w+:", o))
    thumb = next((o[len("thumbnail:"):] for o in outs if o.startswith("thumbnail:")), None)
    infojson = next((o[len("infojson:"):] for o in outs if o.startswith("infojson:")), None)

    def fill(t, ext):
        t = t.replace("%(title).150B", info["title"]).replace("%(title)s", info["title"])
        t = t.replace("%(channel)s", info["channel"]).replace("%(upload_date>%Y)s", "2026")
        t = t.replace("%(upload_date>%Y-%m-%d)s", "2026-03-14")
        return t.replace("%(ext)s", ext)
    path = fill(main, "mkv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\0" * int(os.environ.get("FAKE_YTDLP_SIZE", "1000")))
    if thumb:
        with open(fill(thumb, "jpg"), "wb") as f:
            f.write(b"\xff\xd8\xff")
    if infojson:
        with open(fill(infojson, "") + ".info.json" if not infojson.endswith(".json") else fill(infojson, ""), "w") as f:
            json.dump(info, f)
    print(path)
    sys.exit(0)
sys.exit(2)

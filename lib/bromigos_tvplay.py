"""Find and play an item on the den TV, shared by the guide, media and VECTOR.

Search and resolution run in the caller's worker, never the live layer's drawing thread.
Only public item metadata crosses its socket; adapter credentials stay in the adapter.
"""
import argparse
import json
import re
import sys
import tomllib
import urllib.parse

import bromigos_tv as TV
from bromigos_tvchannels import ChannelError, Store, control

ALIASES = {"scope": "wave", "small": "emblem"}


def screen_name(value):
    value = ALIASES.get(value, value)
    if value not in TV.SCREENS:
        raise ChannelError("Screen: big, scope or small", 2)
    return value


def youtube_url(value):
    u = urllib.parse.urlparse(value)
    return u.scheme == "https" and u.hostname in ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be")


def sources(source=None):
    H = TV._homelab()
    if H is None:
        return []
    names = [source] if source else TV.catalog().get("servers", [])
    return [a for name in names if (a := H.video_source(name)) is not None]


def public_item(item):
    fields = ("id", "title", "series", "season", "episode", "kind", "duration", "year", "server", "position",
              "poster", "thumbnail", "url", "group", "download_source")
    return {k: item[k] for k in fields if item.get(k) is not None}


def search(query="", kind="all", id_=None, source=None, season=None):
    """Titles, seasons or episodes. Downloaded YouTube comes from configured keep folders."""
    out, errors = [], []
    if youtube_url(query):
        return [dict(id=query, title=query, url=query, kind="video", server="youtube")]
    if kind in ("all", "shows", "movies", "seasons", "episodes"):
        for a in sources(source):
            try:
                if kind in ("all", "shows"):
                    out.extend(a.video_shows())
                if kind in ("all", "movies"):
                    out.extend(a.video_movies())
                if kind in ("seasons", "episodes"):
                    rows = a.video_show_items(id_)
                    if kind == "seasons":
                        for n in sorted({int(v.get("season") or 0) for v in rows}):
                            out.append(dict(id=id_, title=f"Season {n}", season=n, kind="season", server=a.name))
                    else:
                        out.extend(v for v in rows if season is None or v.get("season") == season)
            except Exception as e:
                errors.append(f"{a.name}: {type(e).__name__}")
    if kind in ("all", "youtube"):
        import bromigos_youtube as Y
        seen = set()
        for ch in TV.channels(tomllib.loads(Store().load().text)):
            if not ch.get("keep"):
                continue
            for item in (TV.cached_items(ch) or {}).get("items", []):
                if item.get("id") not in seen and Y.kept(ch["keep"], item.get("id")):
                    out.append(dict(item, server="youtube", group=ch["key"]))
                    seen.add(item.get("id"))
        H = TV._homelab()
        if H:
            from bromigos_homelab import registry
            for a in registry.providers("youtube-downloader"):
                try:
                    for source_row in a.sources() or []:
                        for item in a.feed(source_row).get("items", []):
                            if item.get("download"):
                                out.append(dict(id=item["id"], title=item["title"], duration=item.get("duration"),
                                                server=a.name, download_source=source_row.get("uuid"), kind="video"))
                except Exception as e: errors.append(f"{a.name}: {type(e).__name__}")
    q = query.casefold().strip()
    rows = [public_item(v) for v in out if not q or q in TV.label(v).casefold()]
    if not rows and errors:
        raise ChannelError("No results; media source unavailable: " + "; ".join(errors))
    return rows


def downloaded_stream(item):
    """Resolve a Pinchflat enclosure privately; neither tokens nor enclosure URLs leave this call."""
    from bromigos_homelab import registry
    for a in registry.providers("youtube-downloader"):
        if a.name != item.get("server"): continue
        feed = a.feed({"uuid": item["download_source"]})
        rec = next((v for v in feed.get("items", []) if v.get("id") == item["id"]), None)
        if not rec or not rec.get("download"): raise ChannelError("This download is no longer available", 4)
        url = urllib.parse.urljoin(a.endpoint.rstrip("/") + "/", rec["download"])
        if urllib.parse.urlparse(url).netloc != urllib.parse.urlparse(a.endpoint).netloc:
            raise ChannelError("The download points outside its configured source", 2)
        return dict(url=url, headers=a.auth_headers(), title=item["title"], server="YouTube downloads", quality="direct")
    raise ChannelError("Download source is not configured", 4)


def resolve(title=None, id_=None, url=None, source=None):
    if not (title or id_ or url):
        raise ChannelError("Choose a title, --id or --url", 2)
    if url:
        if not youtube_url(url):
            raise ChannelError("Use a YouTube video URL starting with https://", 2)
        return dict(id=url, title=url, url=url, kind="video", server="youtube")
    if id_:
        hits = [public_item(it) for a in sources(source) if (it := a.video_item(id_))]
        if not hits:
            hits = [v for v in search("", "youtube") if v.get("id") == id_ and (not source or v.get("server") == source)]
        if len(hits) == 1:
            return hits[0]
        raise ChannelError("Item not found or its ID belongs to several sources; use --source", 4)
    if youtube_url(title or ""):
        return resolve(url=title)
    episode = re.fullmatch(r"(.+?)\s+(?:S(\d+)E(\d+)|(?:episode|ep)\s*(\d+))", title or "", re.I)
    if episode:
        name, season, ep, plain = episode.groups()
        shows = [v for v in search(name, "shows", source=source) if v["title"].casefold() == name.casefold()]
        hits = []
        for show in shows:
            hits.extend(v for v in search("", "episodes", show["id"], show["server"], int(season or 1))
                        if v.get("episode") == int(ep or plain))
    else:
        hits = [v for v in search(title or "", source=source)
                if v.get("kind") not in ("show", "season") and
                (v["title"].casefold() == (title or "").casefold() or TV.label(v).casefold() == (title or "").casefold())]
    if len(hits) != 1:
        raise ChannelError("No unique playable title. Pick a show’s season and episode, or use --id and --source", 4)
    return hits[0]


def play(screen="big", title=None, id_=None, url=None, source=None, resume=False, item=None):
    screen = screen_name(screen)
    item = public_item(item or resolve(title, id_, url, source))
    if item.get("kind") in ("show", "season"):
        raise ChannelError("Pick an episode to play", 2)
    req = dict(screen=screen, item=item, resume=bool(resume))
    answer = control("tv play-json " + json.dumps(req, separators=(",", ":")))
    if not answer:
        raise ChannelError("The live layer is not running", 3)
    try:
        result = json.loads(answer)
    except ValueError:
        raise ChannelError(answer)
    if not result.get("ok"):
        raise ChannelError(result.get("error") or "Could not play", 1)
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description="Find and play an item now on a den TV screen")
    sub = p.add_subparsers(dest="verb", required=True)
    s = sub.add_parser("search"); s.add_argument("query", nargs="?", default="")
    s.add_argument("--kind", choices=("all", "shows", "movies", "youtube", "seasons", "episodes"), default="all")
    s.add_argument("--id"); s.add_argument("--season", type=int)
    q = sub.add_parser("play"); q.add_argument("title", nargs="?")
    q.add_argument("--id"); q.add_argument("--url"); q.add_argument("--screen", default="big")
    q.add_argument("--resume", action="store_true")
    for parser in (s, q):
        parser.add_argument("--source"); parser.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        result = (dict(ok=True, items=search(args.query, args.kind, args.id, args.source, args.season))
                  if args.verb == "search" else play(args.screen, args.title, args.id, args.url, args.source, args.resume))
        print(json.dumps(result) if args.json else ("\n".join(TV.label(v) for v in result["items"])
                                                   if "items" in result else result.get("message", "Playing")))
        return 0
    except (ChannelError, ValueError, OSError) as e:
        print(json.dumps(dict(ok=False, error=str(e))) if args.json else str(e))
        return getattr(e, "code", 1)


if __name__ == "__main__":
    sys.exit(main())

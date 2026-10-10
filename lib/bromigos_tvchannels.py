"""Shared den TV channel operations for the guide, media, command line and VECTOR.

Channel numbers here are one-based positions in [[tv.channel]], independent of a screen's
TV numbers (its own picture is 1). Names work too. All edits use bromigos_tvconfig's
comment-preserving, checked, atomic writer through the target of a dotfiles symlink.
"""
import argparse
import contextlib
from collections import Counter
import fcntl
import json
import os
import socket
import sys
import time
import tomllib

import bromigos_tv as TV
import bromigos_tvconfig as C

ORDERS = ("shuffle", "in-order", "alternate")
PICK_KEYS = ("shows", "items", "collections")


class ChannelError(ValueError):
    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


def control(command, timeout=2):
    """Talk only to the user's live layer; no process is started or restarted."""
    run = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(timeout)
            s.connect(os.path.join(run, "bromigos-live.sock"))
            s.sendall(command.encode())
            chunks = []
            while b := s.recv(65536):
                chunks.append(b)
            return b"".join(chunks).decode()
    except OSError:
        return None


def live_state():
    out = control("tv state --json")
    try:
        return json.loads(out) if out else None
    except ValueError:
        return None


def _list(value):
    return TV._as_list(value)


def _title(value):
    return str(value).strip().casefold()


def kind(table):
    if table.get("youtube"):
        return "youtube"
    if table.get("files"):
        return "folder"
    if any(table.get(k) for k in PICK_KEYS):
        return "picked"
    if any(table.get(k) for k in ("library", "playlist", "collection")):
        return "library"
    return "picked"       # an empty picked channel is ready to receive its first item


class Store:
    def __init__(self, file=None):
        self.file = file or C.path()
        state = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
        import hashlib
        ident = hashlib.sha256(os.path.realpath(self.file).encode()).hexdigest()[:16]
        self.undo_file = os.path.join(state, "bromigos-live", f"channel-undo-{ident}.json")

    def load(self):
        return C.load(self.file)

    @contextlib.contextmanager
    def locked(self):
        target = os.path.realpath(self.file)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target + ".channels.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def edit(self, change):
        """The guide's existing doc edit, serialized with every other channel edit."""
        with self.locked():
            doc = self.load()
            before = doc.channels()
            result = change(doc)
            after = doc.channels()
            old = Counter(TV._slug(self.display_name(row,i)) for i,row in enumerate(before))
            new = Counter(TV._slug(self.display_name(row,i)) for i,row in enumerate(after))
            if any(count > 1 and count > old[key] for key,count in new.items()):
                raise ChannelError("A channel already has that name", 3)
            previous = {row.get('name') for row in before}
            for row in after:
                if row.get('name') not in previous and ('name' in row):
                    name = str(row['name'] or '').strip()
                    if not name or name.isdecimal() or TV._slug(name) == 'own':
                        raise ChannelError("Give the channel a name other than a number or Own", 2)
            doc.save()
        control("tv reload")
        return result

    @staticmethod
    def display_name(row, index=0):
        channel = TV._entry(row, set())
        return channel['name'] if channel else row.get('name') or f"Channel {index+1}"

    @staticmethod
    def index(doc, channel):
        rows = doc.channels()
        text = str(channel).strip()
        if text.isdecimal():
            n = int(text) - 1
            if 0 <= n < len(rows):
                return n
        hits = [i for i, row in enumerate(rows) if _title(Store.display_name(row,i)) == _title(text)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise ChannelError("Several channels have that name; use its channel number", 3)
        raise ChannelError(f"No channel called {text}", 4)

    @staticmethod
    def unique(doc, name, except_index=None):
        if not str(name).strip() or str(name).strip().isdecimal():
            raise ChannelError("Give the channel a name, rather than only a number", 2)
        slug = TV._slug(str(name))
        if any(i != except_index and TV._slug(Store.display_name(r,i)) == slug
               for i, r in enumerate(doc.channels())):
            raise ChannelError("A channel already has that name", 3)

    def snapshot(self, refresh=False, live=None):
        doc = self.load()
        cfg = tomllib.loads(doc.text)
        tables = doc.channels()
        defaults = TV.screens_of((cfg.get("tv") or {}).get("screens"))
        seen = set()
        live = live_state() if live is None else live
        remembered = TV.state() if not live else {}
        rows = []
        numbers = {s: 1 for s in TV.SCREENS}
        for i, table in enumerate(tables):
            ch = TV._entry(table, seen, defaults)
            if ch is None:
                ch = dict(table, name=table.get("name") or f"Channel {i + 1}", key=TV._slug(table.get("name")),
                          screens=TV.screens_of(table.get("screens"), defaults), order=TV.norm_order(table.get("order")))
            cached = (TV.fetch_items(ch) if refresh and ch.get("kind") else TV.cached_items(ch)) or {}
            items = cached.get("items") or []
            contents = [{"kind": k.rstrip("s"), "title": str(t), "value": t}
                        for k in PICK_KEYS for t in _list(table.get(k))]
            if kind(table) == "picked":
                names = {str(g[0]).split(":", 1)[-1]: g[1] for g in cached.get("groups") or []}
                names.update({str(item.get("id")): item.get("title") for item in items if item.get("kind") != "episode"})
                for content in contents:
                    value = str(content['value'])
                    content['title'] = names.get(value) or content['title']
                    if value.startswith('music:'):
                        _, media_kind, title = value.split(':',2)
                        content.update(title=title, media_kind=media_kind)
                    elif TV.youtube_pick(value):
                        import hashlib
                        content['title'] = names.get(hashlib.sha1(value.encode()).hexdigest()[:16]) or content['title']
            if kind(table) != "picked":
                titles = {}
                for item in items:
                    title = item.get("series") or item.get("title") or str(item.get("id"))
                    titles.setdefault(title, {"kind": item.get("kind"), "title": title, "value": item.get("id")})
                contents = list(titles.values())
            slot = TV.now_next(ch) if ch.get("kind") else None
            tuned, nums, screen_now = [], {}, {}
            for screen in ch["screens"]:
                if ch.get("kind"):
                    numbers[screen] += 1
                    if screen in (live or {}).get('lineups', {}):
                        hit = next((r for r in live['lineups'][screen] if r['key'] == ch['key']),None)
                        if hit: nums[screen] = hit['number']
                    else:
                        nums[screen] = numbers[screen]
                state = ((live or {}).get("screens") or {}).get(screen) or TV.screen_state(remembered, screen)
                if (state.get("key") or state.get("channel")) in (ch["key"], ch["key"] + '-live'):
                    tuned.append(screen)
                    if state.get('now'):
                        screen_now[screen] = {'now':state['now'],'next':state.get('next')}

            current = next(iter(screen_now.values()), {})
            rows.append(dict(number=i + 1, name=ch["name"], key=ch["key"], kind=kind(table),
                             order="alternate" if str(table.get("order") or "").lower().strip() == "alternate" else ch["order"].replace(" ", "-"),
                             bumpers=bool(table.get("bumpers")), screens=ch["screens"], on_screens=tuned,
                             screen_numbers=nums, contents=contents, table=table,
                             now=current.get('now') or (TV.label(slot.item) if slot else None),
                             next=current.get('next') if current else (TV.label(slot.next) if slot else None),
                             screen_now=screen_now,
                             error=cached.get("error"), cached=bool(cached)))
        return {"channels": rows, "running": bool(live), "file": self.file}

    def create(self, name, shows=None, items=None, library=None, youtube=None, folder=None,
               order="shuffle", bumpers=False, source=None, screens=None):
        if order not in ORDERS:
            raise ChannelError("Order must be shuffle, in-order or alternate", 2)
        if youtube and not TV.youtube_pick(youtube):
            raise ChannelError("Give a YouTube video, channel or playlist URL", 2)
        modes = sum(bool(v) for v in (library, youtube, folder)) + bool(shows or items)
        if modes > 1:
            raise ChannelError("Pick shows/items, a library, YouTube, or a folder", 2)
        table = {"name": str(name).strip(), "order": order, "bumpers": bool(bumpers)}
        table.update({k: v for k, v in dict(shows=shows, items=items, library=library, youtube=youtube,
                                          files=folder, source=source, screens=screens).items() if v})
        if modes == 0:
            table["shows"] = []
        def change(doc):
            self.unique(doc, table["name"])
            return doc.add(table) + 1
        n = self.edit(change)
        return {"number": n, "name": table["name"], "message": f"Added channel {table['name']}"}

    def set(self, channel, key, value):
        if key not in ("name", "order", "bumpers", "screens"):
            raise ChannelError("That channel setting cannot be changed", 2)
        if key == "order" and value not in ORDERS:
            raise ChannelError("Order must be shuffle, in-order or alternate", 2)
        def change(doc):
            i = self.index(doc, channel)
            row = doc.channels()[i]
            row["name"] = self.display_name(row,i)
            if key == "name":
                self.unique(doc, value, i)
            doc.set(i, key, value)
            return row
        old = self.edit(change)
        if key == "name":
            control(f"tv rename {TV._slug(old['name'])} {TV._slug(value)}")
        return {"name": value if key == "name" else old["name"], "message": f"Updated {old['name']}: {key}"}

    def item(self, channel, title, remove=False, item_kind="show"):
        title = str(title).strip()
        if not title:
            raise ChannelError("Give the title or URL to add", 2)
        if item_kind == "music" and not title.startswith("music:"):
            title = "music:artist:" + title
        if item_kind == "youtube" and not TV.youtube_pick(title):
            raise ChannelError("Give a YouTube video, channel or playlist URL", 2)
        key = "shows" if item_kind in ("tv", "show", "anime") and not TV.youtube_pick(title) and not title.startswith("music:") else "items"
        aliases = {title}
        if remove:
            for channel_row in self.snapshot(live={})['channels']:
                if _title(channel_row['name']) == _title(channel) or str(channel_row['number']) == str(channel):
                    aliases.update(str(c['value']) for c in channel_row['contents'] if _title(c['title']) == _title(title))
        def change(doc):
            i = self.index(doc, channel)
            row = doc.channels()[i]
            row["name"] = self.display_name(row,i)
            if kind(row) != "picked":
                msg = "Library channels already include their library; choose a picked channel" if kind(row) == "library" \
                    else "Choose a picked channel to add or remove individual titles"
                raise ChannelError(msg, 2)
            keys = PICK_KEYS if remove else (key,)
            changed = False
            for k in keys:
                values = _list(row.get(k))
                have = [v for v in values if _title(v) in {_title(a) for a in aliases} or
                        remove and str(v).startswith('music:') and _title(str(v).split(':',2)[-1]) == _title(title)]
                if remove and have:
                    doc.set(i, k, [v for v in values if v not in have]); changed = True
                elif not remove and not have:
                    doc.set(i, k, values + [title]); changed = True
            if remove and not changed:
                raise ChannelError(f"{title} is not in {row['name']}", 4)
            return row['name']
        name = self.edit(change)
        return {"name": name, "title": title, "message": f"{'Removed' if remove else 'Added'} {title} "
                f"{'from' if remove else 'to'} {name}"}

    def move(self, channel, position):
        def change(doc):
            i = self.index(doc, channel)
            n = int(position) - 1
            if not 0 <= n < len(doc.channels()):
                raise ChannelError("Position is outside the channel list", 2)
            name = self.display_name(doc.channels()[i],i); doc.move(i, n); return name
        name = self.edit(change)
        return {"name": name, "message": f"Moved {name} to {position}"}

    def move_item(self, channel, title, position):
        def change(doc):
            i = self.index(doc, channel); row = doc.channels()[i]
            for key in PICK_KEYS:
                vals = _list(row.get(key))
                j = next((n for n, v in enumerate(vals) if _title(v) == _title(title)), None)
                if j is not None:
                    pos = int(position) - 1
                    if not 0 <= pos < len(vals):
                        raise ChannelError("Position is outside this picked list", 2)
                    vals.insert(pos, vals.pop(j)); doc.set(i, key, vals); return self.display_name(row,i)
            raise ChannelError("That item is not in the channel", 4)
        name = self.edit(change)
        return {"name": name, "message": f"Moved {title} to {position}"}

    def remove(self, channel):
        def change(doc):
            i = self.index(doc, channel); name = self.display_name(doc.channels()[i],i)
            idx, text = doc.remove(i)
            TV._write_json(self.undo_file, {"index": idx, "text": text, "name": name})
            return name
        name = self.edit(change)
        return {"name": name, "message": f"Removed channel {name}. Use channel undo to restore it"}

    def undo(self):
        try:
            with open(self.undo_file) as f:
                back = json.load(f)
        except (OSError, ValueError):
            raise ChannelError("No deleted channel to undo", 4) from None
        def change(doc):
            self.unique(doc, back['name']); doc.restore(back['index'], back['text'])
        self.edit(change); os.unlink(self.undo_file)
        return {"name": back['name'], "message": f"Restored {back['name']}"}

    def tune(self, channel, screen="big"):
        screen = {"scope": "wave", "small": "emblem"}.get(screen, screen)
        if screen not in TV.SCREENS:
            raise ChannelError("Screen must be big, wave or emblem", 2)
        doc = self.load(); i = self.index(doc, channel)
        row = self.snapshot()['channels'][i]
        n = row['screen_numbers'].get(screen)
        if n is None:
            raise ChannelError("This channel is not available on that screen", 2)
        return tune_number(n, screen)


def tune_number(number, screen=None):
    screen = {"scope": "wave", "small": "emblem"}.get(screen, screen)
    if (screen is not None and screen not in TV.SCREENS) or int(number) < 1:
        raise ChannelError("Give a channel number and screen big, wave or emblem", 2)
    answer = control(f"tv set {int(number)}" + (f" --screen {screen}" if screen else ""))
    if answer is None:
        raise ChannelError("The live layer is not running; start it before tuning")
    if answer.startswith(('no ', 'bromigos-live ')):
        raise ChannelError(answer)
    return {"screen": screen, "channel": int(number), "message": answer}


def membership(title, rows):
    return [r for r in rows if any(_title(p['value']) == _title(title) or _title(p['title']) == _title(title) or
                                 str(p['value']).startswith('music:') and _title(str(p['value']).split(':',2)[-1]) == _title(title)
                                 for p in r['contents'])]


def parser():
    p = argparse.ArgumentParser(prog="bromigos-live tv", description="Read and edit den TV channels without a restart")
    sub = p.add_subparsers(dest="verb", required=True)
    c = sub.add_parser("channels", help="Every channel, contents, order, screens and now/next")
    c.add_argument("--json", action="store_true"); c.add_argument("--refresh", action="store_true", help="Read content from servers now")
    c = sub.add_parser("set", help="Tune a channel number on a screen")
    c.add_argument("number", type=int); c.add_argument("--screen"); c.add_argument("--json", action="store_true")
    c = sub.add_parser("channel", help="Add, edit, delete and restore channels")
    subs = c.add_subparsers(dest="action", required=True)
    for name in ('add','rename','remove','order','bumpers','move','add-item','remove-item','move-item','tune','undo'):
        q = subs.add_parser(name)
        q.add_argument("--json", action="store_true")
        if name not in ('add','undo'):
            q.add_argument("channel", metavar="NAME|N")
        if name == 'add':
            q.add_argument('name'); q.add_argument('--shows',nargs='+'); q.add_argument('--items',nargs='+')
            for k in ('library','youtube','folder','source'):
                q.add_argument('--'+k)
            q.add_argument('--order',choices=ORDERS,default='shuffle'); q.add_argument('--bumpers',action='store_true')
            q.add_argument('--screens',nargs='+',choices=TV.SCREENS)
        elif name in ('add-item','remove-item','move-item'):
            q.add_argument('title')
            if name == 'add-item': q.add_argument('--kind',choices=('show','movie','music','youtube'),default='show')
            if name == 'move-item': q.add_argument('position',type=int)
        elif name == 'rename': q.add_argument('name')
        elif name == 'order': q.add_argument('value',choices=ORDERS)
        elif name == 'bumpers': q.add_argument('value',choices=('on','off'))
        elif name == 'move': q.add_argument('position',type=int)
        elif name == 'remove': q.add_argument('--yes',action='store_true')
        elif name == 'tune': q.add_argument('--screen',default='big')
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    js = '--json' in argv
    try:
        try:
            a = parser().parse_args(argv)
        except SystemExit as e:
            if e.code and js: print(json.dumps({'error':'Invalid arguments; see --help','code':2}))
            return e.code
        store = Store()
        if a.verb == 'channels':
            result = store.snapshot(refresh=a.refresh)
        elif a.verb == 'set':
            result = tune_number(a.number,a.screen)
        elif a.action == 'add':
            result = store.create(a.name,a.shows,a.items,a.library,a.youtube,a.folder,a.order,a.bumpers,a.source,a.screens)
        elif a.action == 'rename': result = store.set(a.channel,'name',a.name)
        elif a.action == 'order': result = store.set(a.channel,'order',a.value)
        elif a.action == 'bumpers': result = store.set(a.channel,'bumpers',a.value=='on')
        elif a.action == 'move': result = store.move(a.channel,a.position)
        elif a.action == 'move-item': result = store.move_item(a.channel,a.title,a.position)
        elif a.action == 'add-item': result = store.item(a.channel,a.title,item_kind=a.kind)
        elif a.action == 'remove-item': result = store.item(a.channel,a.title,remove=True)
        elif a.action == 'tune': result = store.tune(a.channel,a.screen)
        elif a.action == 'undo': result = store.undo()
        elif a.action == 'remove':
            doc = store.load(); index = store.index(doc,a.channel)
            row = doc.channels()[index]; row['name'] = store.display_name(row,index)
            if not a.yes:
                if not sys.stdin.isatty() or input(f"Remove channel {row['name']}? Type its name: ").strip() != row['name']:
                    raise ChannelError('Nothing removed; use --yes to confirm',2)
            result = store.remove(a.channel)
        if js: print(json.dumps(result,ensure_ascii=False))
        elif 'channels' in result:
            for r in result['channels']:
                print(f"{r['number']:>2} {r['name']} ({r['kind']}, {r['order']}, bumpers {'on' if r['bumpers'] else 'off'})")
                print('   Screens: '+', '.join(r['screens'])+'; on: '+(', '.join(r['on_screens']) or 'none'))
                print('   Now: '+(r['now'] or 'not cached')+'; next: '+(r['next'] or 'not cached'))
                print('   Contents: '+(', '.join(c['title'] for c in r['contents']) or 'empty / not cached'))
        else: print(result['message'])
        return 0
    except (ChannelError,C.ConfigError,OSError,ValueError) as e:
        code = getattr(e,'code',1)
        if js: print(json.dumps({'error':str(e),'code':code}))
        else: print(str(e),file=sys.stderr)
        return code


if __name__ == '__main__':
    sys.exit(main())

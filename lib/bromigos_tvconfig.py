"""The den TV's channels, written in place: the [[tv.channel]] tables of the live layer's
config (~/.config/bromigos-live/config.toml), changed without touching anything else.

The channel guide (Settings › Den TV) adds, removes, reorders, renames and moves channels
between screens through this. The file is edited as text, a channel table at a time, so
every comment, blank line and other table stays exactly as it was: a channel's own
comments (the lines right above its [[tv.channel]] line, and those inside it) go with it
when it moves or is removed; the comments above the first of a run of channels introduce
them all and stay put. Each save is checked first: the new file must parse, and
everything but the channels must read the same as before. It's written atomically (a
temporary file, then a rename) to the file a symlink points at, so a dotfiles link stays
a link. The live layer sees the change and reads the channels again, without a restart.

    import bromigos_tvconfig as C
    doc = C.load()                       # C.Doc for config.toml (an empty one when it's missing)
    doc.channels()                       # [{name, library, screens, …}] as written
    doc.add({"name": "Sitcoms", "shows": ["Example Show"], "order": "in order"})
    undo = doc.remove(2)                 # (index, the table's text): doc.restore(*undo) puts it back
    doc.move(3, 0)                       # channel 3 becomes the first
    doc.set(0, "screens", ["big", "wave"])
    doc.set(0, "order", None)            # None: the key goes
    doc.save()                           # checked, atomic, through the symlink

Values are strings, numbers, booleans and lists of those (the channel keys there are).
"""
import json
import os
import re
import tempfile
import tomllib

HEADER = re.compile(r"^\s*\[")
CHANNEL = re.compile(r"^\s*\[\[\s*tv\s*\.\s*channel\s*\]\]\s*(#.*)?$")
KEY = re.compile(r"^(\s*)([A-Za-z0-9_-]+|\"[^\"]*\")\s*=\s*")


class ConfigError(ValueError):
    """The change would make a file that doesn't parse, or changes more than the channels."""


def path():
    """The live layer's user config (BROMIGOS_LIVE_CONFIG, else ~/.config/bromigos-live/config.toml)."""
    return os.environ.get("BROMIGOS_LIVE_CONFIG") or os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "bromigos-live", "config.toml")


def value(v):
    """A TOML value for v (a string, number, boolean, or a list of those)."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(value(x) for x in v) + "]"
    raise ConfigError(f"can't write {v!r} in a channel")


def _string_end(s, c, q):
    """Just past the string that opens with q at s[c] on one line, or None."""
    k = c + len(q)
    while k < len(s):
        if q == '"' and s[k] == "\\":
            k += 2
            continue
        if s.startswith(q, k):
            return k + len(q)
        k += 1
    return None


def _value_end(lines, i, col):
    """(line, column) just past the value that starts at lines[i][col]: a multi-line
    string, an array or an inline table may run over several lines."""
    s = lines[i]
    if s.startswith(('"""', "'''"), col):
        q = s[col:col + 3]
        k = s.find(q, col + 3)
        j = i
        while k < 0 and j + 1 < len(lines):
            j += 1
            k = lines[j].find(q)
        return (j, k + 3) if k >= 0 else (j, len(lines[j]))
    if s[col:col + 1] in ("\"", "'"):
        e = _string_end(s, col, s[col])
        return i, e if e is not None else len(s.rstrip("\n"))
    if s[col:col + 1] in ("[", "{"):
        depth, j, c = 0, i, col
        while j < len(lines):
            t = lines[j]
            while c < len(t):
                ch = t[c]
                if ch in "\"'":
                    e = _string_end(t, c, ch)
                    c = e if e is not None else len(t)
                    continue
                if ch == "#":
                    break
                if ch in "[{":
                    depth += 1
                elif ch in "]}":
                    depth -= 1
                    if depth == 0:
                        return j, c + 1
                c += 1
            j += 1
            c = 0
        return len(lines) - 1, len(lines[-1])
    m = re.match(r"[^\s#]*", s[col:])
    return i, col + m.end()


class Doc:
    def __init__(self, text="", file=None):
        self.file = file or path()
        self.text = text
        self.original = text

    # -- reading
    def _lines(self):
        return self.text.splitlines(keepends=True)

    def blocks(self):
        """[(start, header, end)] line indexes of each [[tv.channel]] table: start is its first
        comment line (the comments right above its header), end is where the next table's
        comments (or header) begin."""
        lines = self._lines()
        heads = [i for i, ln in enumerate(lines) if HEADER.match(ln) and not ln.lstrip().startswith("#")]

        def lead(h):
            k = h
            while k > 0 and lines[k - 1].lstrip().startswith("#"):
                k -= 1
            return k
        out = []
        for n, h in enumerate(heads):
            if not CHANNEL.match(lines[h]):
                continue
            nxt = heads[n + 1] if n + 1 < len(heads) else None
            end = len(lines) if nxt is None else lead(nxt)     # the next table's comments are its own
            # the comments above the first channel after another table (or the file's top)
            # introduce the channels as a whole: they stay where they are
            first = n == 0 or not CHANNEL.match(lines[heads[n - 1]])
            start = h if first else lead(h)
            if end < h + 1:
                end = h + 1
            out.append((start, h, end))
        return out

    def channels(self):
        """Each [[tv.channel]] table as written (a dict)."""
        try:
            return list((tomllib.loads(self.text).get("tv") or {}).get("channel") or [])
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{self.file} doesn't parse: {e}") from None

    def _block_text(self, i):
        b = self.blocks()[i]
        return "".join(self._lines()[b[0]:b[2]])

    # -- changing
    def add(self, table, index=None):
        """A new channel from a dict, after the last one (or at index); its index."""
        body = "[[tv.channel]]\n" + "".join(f"{k} = {value(v)}\n" for k, v in table.items() if v not in (None, ""))
        return self._insert(body, index)

    def _insert(self, body, index=None):
        lines = self._lines()
        bl = self.blocks()
        if not body.endswith("\n"):
            body += "\n"
        if index is not None and index < len(bl):
            at = bl[index][0]
            lines[at:at] = [body if body.endswith("\n\n") else body + "\n"]
            self.text = "".join(lines)
            return index
        if bl:
            at = bl[-1][2]
            prev = "".join(lines[:at])
            if not prev.endswith("\n\n"):
                body = "\n" + body
            lines[at:at] = [body]
        else:
            text = self.text
            if text and not text.endswith("\n"):
                text += "\n"
            if text and not text.endswith("\n\n"):
                text += "\n"
            self.text = text + body
            return 0
        self.text = "".join(lines)
        return len(bl)

    def remove(self, i):
        """Take channel i out: (i, its text), for restore()."""
        lines = self._lines()
        s, _h, e = self.blocks()[i]
        gone = "".join(lines[s:e])
        del lines[s:e]
        self.text = "".join(lines)
        return i, gone

    def restore(self, i, text):
        """Put a removed channel back where it was."""
        self._insert(text, i)

    def move(self, i, j):
        """Channel i to position j (the others keep their order). Each table moves with its
        own comments; the slots they sit in stay where they are in the file."""
        bl = self.blocks()
        if not (0 <= i < len(bl)) or not (0 <= j < len(bl)) or i == j:
            return
        lines = self._lines()
        texts = ["".join(lines[s:e]) for s, _h, e in bl]
        for k, t in enumerate(texts):                  # each ends in one blank line, wherever it lands
            texts[k] = t.rstrip("\n") + "\n\n"
        t = texts.pop(i)
        texts.insert(j, t)
        out, last = [], 0
        for (s, _h, e), t in zip(bl, texts):
            out.append("".join(lines[last:s]))
            out.append(t)
            last = e
        tail = "".join(lines[last:])
        if not tail:                                   # the file ends with a channel: one newline
            out[-1] = out[-1].rstrip("\n") + "\n"
        out.append(tail)
        self.text = "".join(out)

    def set(self, i, key, val):
        """Set (or with None, remove) a key of channel i, keeping its comment on the line."""
        lines = self._lines()
        s, h, e = self.blocks()[i]
        for n in range(h + 1, e):
            m = KEY.match(lines[n])
            if not m or m.group(2).strip('"') != key:
                continue
            j, c = _value_end(lines, n, m.end())
            if val is None:
                del lines[n:j + 1]
            else:
                rest = lines[j][c:]
                lines[n:j + 1] = [lines[n][:m.end()] + value(val) + (rest if rest.strip() else "\n")]
            self.text = "".join(lines)
            return
        if val is None:
            return
        last = h
        for n in range(h + 1, e):                       # after the table's last key
            if KEY.match(lines[n]):
                last = _value_end(lines, n, KEY.match(lines[n]).end())[0]
        lines.insert(last + 1, f"{key} = {value(val)}\n")
        self.text = "".join(lines)

    # -- writing
    def check(self):
        """The new text parses, and nothing but the channels reads differently."""
        try:
            new = tomllib.loads(self.text)
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"the change wouldn't parse ({e}); nothing written") from None
        try:
            old = tomllib.loads(self.original)
        except tomllib.TOMLDecodeError:
            old = None
        if old is not None:
            def rest(d):
                d = json.loads(json.dumps(d, default=str))
                (d.get("tv") or {}).pop("channel", None)
                if d.get("tv") == {}:
                    d.pop("tv")
                return d
            if rest(old) != rest(new):
                raise ConfigError("the change would touch more than the channels; nothing written")
        return new

    def save(self):
        """Write it (checked first), atomically, to the file the path's symlink points at."""
        self.check()
        real = os.path.realpath(self.file)
        os.makedirs(os.path.dirname(real), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(real), prefix=".config.toml.")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(self.text)
            try:
                os.chmod(tmp, os.stat(real).st_mode & 0o777)
            except OSError:
                os.chmod(tmp, 0o644)
            os.replace(tmp, real)
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
        self.original = self.text
        return real


def load(file=None):
    """The config as a Doc (empty when it isn't there yet)."""
    file = file or path()
    try:
        with open(file) as f:
            return Doc(f.read(), file)
    except FileNotFoundError:
        return Doc("", file)

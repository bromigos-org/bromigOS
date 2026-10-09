"""__TITLE__: tools for VECTOR (made by `bromigos ext new vector-tool`; docs/extensions.md).

VECTOR imports this at his start (bromigos restart vector) and calls register(vector).
A tool is a name (lower_snake_case, 3-40 characters), a description he reads to decide
when to use it, a JSON schema for its arguments, a function, and a level: "read" (looks
things up) or "desktop" (changes this desktop), never the terminal. Every call goes
through his audit log and event feed, like his own tools. The extension is protected
like his own plugins: hand-edit the installed copy and his terminal switches off; change
it here, commit, and `bromigos ext update`.
"""
import os


def uptime():
    """-> how long this machine has been up, and its load average."""
    with open("/proc/uptime") as f:
        secs = float(f.read().split()[0])
    days, rest = divmod(int(secs), 86400)
    return {"up_seconds": int(secs), "up": f"{days}d {rest // 3600}h {rest % 3600 // 60}m",
            "load_1_5_15": [round(x, 2) for x in os.getloadavg()], "cpus": os.cpu_count()}


def register(vector):
    vector.tool("__IDENT___uptime",
                "How long this machine has been up, its load average (1, 5, 15 minutes) and CPU count.",
                {"type": "object", "properties": {}, "required": []},
                uptime, level="read")

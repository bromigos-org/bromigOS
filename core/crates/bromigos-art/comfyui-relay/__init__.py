"""bromigos-relay: a ComfyUI custom node with no nodes (docs/activity.md, "Lab jobs").

ComfyUI sends a prompt's progress (executing, progress, progress_state, executed) and the
preview frames it streams while sampling only to the client that queued the prompt. This copies
them to the watchers that know the relay's token: clients connected as
`bromigos-watch-<token>-<anything>`, four at most. So `bromigos activity watch`, the Lab board and
the start page can show any prompt live, whoever queued it. It changes nothing else: what each
client already got, it still gets, once.

The token is the first line of the file named by BROMIGOS_RELAY_TOKEN_FILE, or the variable
BROMIGOS_RELAY_TOKEN, or the file `token` beside this one (where the Creation studio puts it):
at least 16 letters and digits. Without one the relay copies nothing. The
watchers read the same token (labjobs.toml's `relay_token`, a reference such as
"@file:/etc/bromigos/comfyui-relay.token").

Install: link this folder into ComfyUI's custom_nodes/, set the token, and restart ComfyUI:

    ln -s /usr/share/bromigos/art/comfyui-relay /path/to/ComfyUI/custom_nodes/bromigos-relay

Previews exist only when ComfyUI makes them: start it with --preview-method auto, or queue
with "extra_data": {"preview_method": "auto"} (bromigos art does).
"""
import hmac
import os
import re

WATCH_PREFIX = "bromigos-watch-"
MAX_WATCHERS = 4
TOKEN_OK = re.compile(r"[A-Za-z0-9]{16,128}\Z")
EVENTS = frozenset(("execution_start", "execution_cached", "executing", "progress", "progress_state", "executed",
                    "execution_success", "execution_error", "execution_interrupted"))
PREVIEWS = frozenset((1, 4))     # protocol.BinaryEventTypes: PREVIEW_IMAGE, PREVIEW_IMAGE_WITH_METADATA

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}


HERE_TOKEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token")


def read_token(environ=None, beside=HERE_TOKEN):
    """The relay's token, or None (then it copies nothing)."""
    e = os.environ if environ is None else environ
    token = e.get("BROMIGOS_RELAY_TOKEN") or ""
    path = e.get("BROMIGOS_RELAY_TOKEN_FILE") or (beside if not token else None)
    if path:
        try:
            with open(path) as f:
                token = f.readline().strip()
        except OSError:
            token = ""
    return token if TOKEN_OK.match(token) else None


def watchers(server, sid, token):
    """The sockets that named the token (bromigos-watch-<token>-…), four at most, never `sid`."""
    want = WATCH_PREFIX + token + "-"
    out = []
    for k in list(server.sockets):
        if isinstance(k, str) and k != sid and len(k) > len(want) and hmac.compare_digest(k[:len(want)], want):
            out.append(k)
            if len(out) >= MAX_WATCHERS:
                break
    return out


def install(server, token=None):
    """Wrap the server's send_json and send_bytes once. Returns whether it did."""
    token = token if token is not None else read_token()
    if getattr(server, "_bromigos_relay", False) or not token:
        return False
    send_json, send_bytes = server.send_json, server.send_bytes

    async def relay_json(event, data, sid=None):
        await send_json(event, data, sid)
        if sid is not None and event in EVENTS:      # None went to everyone already
            for k in watchers(server, sid, token):
                await send_json(event, data, k)

    async def relay_bytes(event, data, sid=None):
        await send_bytes(event, data, sid)
        if sid is not None and event in PREVIEWS:
            for k in watchers(server, sid, token):
                await send_bytes(event, data, k)

    server.send_json, server.send_bytes = relay_json, relay_bytes
    server._bromigos_relay = True
    return True


try:
    from server import PromptServer          # ComfyUI's own module, when ComfyUI loads this

    if getattr(PromptServer, "instance", None) is not None:
        install(PromptServer.instance)
except ImportError:                          # imported outside ComfyUI (the tests)
    pass

"""bromigos-relay: a ComfyUI custom node with no nodes (docs/activity.md, "Lab jobs").

ComfyUI sends a prompt's progress (executing, progress, progress_state, executed) and the
preview frames it streams while sampling only to the client that queued the prompt. This copies
them to every client connected as `bromigos-watch-<anything>`, so `bromigos activity watch`,
the Lab board and the start page can show any prompt live, whoever queued it. It changes
nothing else: what each client already got, it still gets, once.

Install: link this folder into ComfyUI's custom_nodes/ and restart ComfyUI:

    ln -s /usr/share/bromigos/art/comfyui-relay /path/to/ComfyUI/custom_nodes/bromigos-relay

Previews exist only when ComfyUI makes them: start it with --preview-method auto, or queue
with "extra_data": {"preview_method": "auto"} (bromigos art does).
"""
WATCH_PREFIX = "bromigos-watch-"
EVENTS = frozenset(("execution_start", "execution_cached", "executing", "progress", "progress_state", "executed",
                    "execution_success", "execution_error", "execution_interrupted"))
PREVIEWS = frozenset((1, 4))     # protocol.BinaryEventTypes: PREVIEW_IMAGE, PREVIEW_IMAGE_WITH_METADATA

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}


def watchers(server, sid):
    return [k for k in list(server.sockets) if isinstance(k, str) and k.startswith(WATCH_PREFIX) and k != sid]


def install(server):
    """Wrap the server's send_json and send_bytes once. Returns whether it did."""
    if getattr(server, "_bromigos_relay", False):
        return False
    send_json, send_bytes = server.send_json, server.send_bytes

    async def relay_json(event, data, sid=None):
        await send_json(event, data, sid)
        if sid is not None and event in EVENTS:      # None went to everyone already
            for k in watchers(server, sid):
                await send_json(event, data, k)

    async def relay_bytes(event, data, sid=None):
        await send_bytes(event, data, sid)
        if sid is not None and event in PREVIEWS:
            for k in watchers(server, sid):
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

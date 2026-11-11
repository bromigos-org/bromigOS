"""The board's API (docs/board.md, "The API"): Starlette, served by uvicorn on the Unix socket
systemd hands bromigos-board.service, as the unprivileged user bromigos-board. Caddy is the only
client: it serves the page's files and passes /api here.

  GET    /api/door            anyone on the home network: the server's name and app tiles
  GET    /api/session         whether this browser is signed in, and the browsers that are
  POST   /api/session         sign in with a code from `sudo bromigos server board code`
  DELETE /api/session         sign this browser out
  DELETE /api/session/{id}    sign another browser out
  GET    /api/board           everything the board shows (signed in)
  GET    /api/activity        the jobs, live, as server-sent events (signed in)

Every answer is JSON with Cache-Control: no-store. An error is {"error": {"code", "words"}}.
A request from an address that isn't private gets 403 whatever it asks for; every request that
isn't a GET passes the CSRF check first.
"""
import asyncio
import json
import os
import time

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from . import SCHEMA, auth, board, door, net, paths

READ_METHODS = ("GET", "HEAD", "OPTIONS")
BODY_MAX = 4096
KEEP_ALIVE_S = 20               # a comment line this often keeps an activity stream open through proxies
TOUCH_EVERY_S = 15              # how often an open activity stream says a browser is connected
CSRF_HEADER = "x-bromigos-board"    # every request that changes something carries it: "1"
API_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
               "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'"}

NOT_LOCAL = ("not-local", "The Lab board answers only the home network and the lab's private network.")
SIGNED_OUT = ("signed-out", "Sign in first: run sudo bromigos server board code at the server, and type the code here.")
CSRF = ("csrf", "This request didn't come from the board's own page, so it was refused.")
BAD_CODE = ("bad-code", "That code isn't right, or it was used already. "
                        "Run sudo bromigos server board code at the server for a new one.")
EXPIRED = ("expired", "That code is older than 10 minutes. Run sudo bromigos server board code at the server for a new one.")


def error(status, what, headers=None):
    code, words = what
    return JSONResponse({"error": {"code": code, "words": words}}, status_code=status, headers=headers)


class LocalOnly:
    """ASGI middleware: refuse any source address that isn't private (net.is_private), and give
    every answer the API's headers."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def with_headers(message):
            if message["type"] == "http.response.start":
                have = {k.lower() for k, _ in message.get("headers", [])}
                message["headers"] = list(message.get("headers", [])) + [
                    (k.lower().encode(), v.encode()) for k, v in API_HEADERS.items() if k.lower().encode() not in have]
            await send(message)

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        peer = (scope.get("client") or (None,))[0]
        if not net.is_private(net.source(headers, peer)):
            return await error(403, NOT_LOCAL)(scope, receive, with_headers)
        return await self.app(scope, receive, with_headers)


def touch_wanted():
    """Say a browser is connected, so the root-run snapshot reads the server (bromigos-board-snapshot.path)."""
    p = paths.at(paths.WANTED)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a"):
            pass
        os.utime(p)
    except OSError:
        pass


def read_snapshot():
    doc = paths.read_json(paths.at(paths.SNAPSHOT))
    return doc if isinstance(doc, dict) else None


def session_of(request):
    return auth.session_for(request.cookies.get(auth.COOKIE))


def source_of(request):
    return net.source(request.headers, request.client.host if request.client else None)


def csrf_ok(request):
    """Every request that changes something comes from the board's own page: it carries
    X-Bromigos-Board: 1, which a page on another site can't send without a CORS answer this API
    never gives; its Origin, when the browser sends one, is this page's; its Sec-Fetch-Site, when
    sent, is same-origin; and its body is JSON (json_body), which a plain form can't send. The
    session cookie is SameSite=Strict besides."""
    if request.method in READ_METHODS:
        return True
    if request.headers.get(CSRF_HEADER) != "1":
        return False
    origin = request.headers.get("origin")
    if origin is not None and origin != f"https://{request.headers.get('host', '')}":
        return False
    return request.headers.get("sec-fetch-site", "same-origin") in ("same-origin", "none")


async def json_body(request):
    """(dict, None) or (None, an error response)."""
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        return None, error(415, ("not-json", "Send JSON (Content-Type: application/json)."))
    body = await request.body()
    if len(body) > BODY_MAX:
        return None, error(413, ("too-big", "That request is too big."))
    try:
        doc = json.loads(body or b"{}")
    except ValueError:
        return None, error(400, ("bad-json", "That isn't JSON."))
    if not isinstance(doc, dict):
        return None, error(400, ("bad-json", "Send a JSON object."))
    return doc, None


def set_session_cookie(response, value):
    response.set_cookie(auth.COOKIE, value, max_age=auth.SESSION_MS // 1000, path="/", secure=True, httponly=True,
                        samesite="strict")


SIGNED_OUT_DOC = {"schema": SCHEMA, "signed_in": False, "role": None, "browser": None, "expires_at": None, "browsers": []}


def session_doc(rec):
    """This browser's session and every browser signed in (People › Ways in)."""
    return {"schema": SCHEMA, "signed_in": True, "role": "owner",
            "browser": {"id": rec["id"], "name": rec["browser"]}, "expires_at": rec["expires_at"],
            "browsers": [{"id": s["id"], "name": s["browser"], "signed_in_at": s["created_at"],
                          "last_seen_at": s["last_seen_at"], "expires_at": s["expires_at"], "current": s["id"] == rec["id"]}
                         for s in auth.sessions()]}


# ---------------------------------------------------------------- endpoints
async def get_door(request):
    touch_wanted()
    return JSONResponse(door.door(read_snapshot()))


async def get_session(request):
    rec = session_of(request)
    return JSONResponse(session_doc(rec) if rec else dict(SIGNED_OUT_DOC))


async def post_session(request):
    if not csrf_ok(request):
        return error(403, CSRF)
    doc, bad = await json_body(request)
    if bad:
        return bad
    src = source_of(request)
    tries = request.app.state.tries
    why = tries.blocked(src)
    if why:
        return error(429, ("too-many", why), headers={"Retry-After": "60"})
    result = await run_in_threadpool(auth.use_code, doc.get("code"))
    if result is not True:
        tries.wrong(src)
        return error(401, EXPIRED if result == "expired" else BAD_CODE)
    value, rec = await run_in_threadpool(auth.new_session, request.headers.get("user-agent", ""))
    r = JSONResponse(session_doc(rec))
    set_session_cookie(r, value)
    return r


async def delete_session(request):
    rec = session_of(request)
    if not rec:
        return error(401, SIGNED_OUT)
    if not csrf_ok(request):
        return error(403, CSRF)
    auth.end_session(rec["id"])
    r = JSONResponse(dict(SIGNED_OUT_DOC))
    r.delete_cookie(auth.COOKIE, path="/", secure=True, httponly=True, samesite="strict")
    return r


async def delete_session_id(request):
    """Sign another browser out (or this one: then it's signed out, as DELETE /api/session)."""
    rec = session_of(request)
    if not rec:
        return error(401, SIGNED_OUT)
    if not csrf_ok(request):
        return error(403, CSRF)
    sid = request.path_params["sid"]
    if sid == rec["id"]:
        return await delete_session(request)
    if not auth.end_session(sid):
        return error(404, ("no-session", "No browser is signed in with that id."))
    return JSONResponse(session_doc(rec))


async def get_board(request):
    rec = session_of(request)
    if not rec:
        return error(401, SIGNED_OUT)
    touch_wanted()
    snap = read_snapshot()
    if snap is None:
        return error(503, ("gathering", "The board is reading this server. It's ready in a few seconds."),
                     headers={"Retry-After": "5"})
    return JSONResponse(board.shape(snap, paths.now_ms()))


def _activity():
    import bromigos_activity
    return bromigos_activity


def jobs_now(limit=50):
    try:
        A = _activity()
        return A.list_jobs(A.Env(), limit=limit)
    except Exception:          # no bromigos-core here, or an unreadable folder: no jobs, not a crash
        return []


def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


async def activity_events(request, cookie, poll=1.0, limit_s=None):
    """`snapshot` with the list first; then `job` for each record that changed and `gone` for one
    that was pruned; `signed-out` (and the end) when the session ends. A comment line every 20
    seconds keeps the connection open through proxies."""
    jobs = await run_in_threadpool(jobs_now)
    seen = {j["id"]: j.get("updated_at") for j in jobs}
    yield sse("snapshot", {"schema": SCHEMA, "jobs": jobs})
    start = last_touch = last_alive = time.monotonic()
    touch_wanted()
    while limit_s is None or time.monotonic() - start < limit_s:
        await asyncio.sleep(poll)
        if await request.is_disconnected():
            return
        now = time.monotonic()
        if now - last_touch >= TOUCH_EVERY_S:
            last_touch = now
            if not auth.session_for(cookie):
                yield sse("signed-out", {"words": SIGNED_OUT[1]})
                return
            touch_wanted()
        if now - last_alive >= KEEP_ALIVE_S:
            last_alive = now
            yield ": keep-alive\n\n"
        jobs = await run_in_threadpool(jobs_now)
        ids = set()
        for j in jobs:
            ids.add(j["id"])
            if seen.get(j["id"], object()) != j.get("updated_at"):
                seen[j["id"]] = j.get("updated_at")
                yield sse("job", j)
        for gone in [i for i in seen if i not in ids]:
            del seen[gone]
            yield sse("gone", {"id": gone})


async def get_activity(request):
    rec = session_of(request)
    if not rec:
        return error(401, SIGNED_OUT)
    st = request.app.state
    gen = activity_events(request, request.cookies.get(auth.COOKIE), poll=st.poll, limit_s=st.stream_s)
    return StreamingResponse(gen, media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


ROUTES = [
    Route("/api/door", get_door, methods=["GET"]),
    Route("/api/session", get_session, methods=["GET"]),
    Route("/api/session", post_session, methods=["POST"]),
    Route("/api/session", delete_session, methods=["DELETE"]),
    Route("/api/session/{sid}", delete_session_id, methods=["DELETE"]),
    Route("/api/board", get_board, methods=["GET"]),
    Route("/api/activity", get_activity, methods=["GET"]),
]


def make_app(tries=None, poll=1.0, stream_s=None):
    """The app. `stream_s` ends an activity stream after that many seconds (tests); None: never."""
    app = Starlette(routes=list(ROUTES))
    app.state.tries = tries or auth.Tries()
    app.state.poll = poll
    app.state.stream_s = stream_s
    return LocalOnly(app)

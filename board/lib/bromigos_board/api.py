"""The board's API (docs/board.md, "The API"): Starlette, served by uvicorn on the Unix socket
systemd hands bromigos-board.service, as the unprivileged user bromigos-board. Caddy is the only
client: it serves the page's files and passes /api here.

  GET    /api/door            anyone on the home network: the server's name and app tiles
  GET    /api/local           204 for an address the board answers (Caddy asks, for the lab's network)
  GET    /api/session         whether this browser is signed in, and the browsers that are
  POST   /api/session         sign in with a code from `sudo bromigos server board code`
  DELETE /api/session         sign this browser out
  DELETE /api/session/{id}    sign another browser out
  GET    /api/board           everything the board shows (signed in)
  GET    /api/activity        the jobs, live, as server-sent events (signed in)
  POST   /api/actions         {verb, app[, delete_data, code]}: restart, add or remove an app, as a
                              job (signed in; deleting its data needs a fresh console code too)
  POST   /api/activity/{job}/answer   {question, choice}: answer what a job asks (signed in)
  POST   /api/activity/{job}/cancel   {}: stop a job that says stopping is safe (signed in)
  POST   /api/activity/{job}/retry    {}: start again a job that ended badly and may be (signed in)

Every answer is JSON with Cache-Control: no-store. An error is {"error": {"code", "words"}}.
A request from an address that isn't private gets 403 whatever it asks for; every request that
isn't a GET passes the CSRF check first, and its body is read up to 4096 bytes and no further.
"""
import asyncio
import contextlib
import json
import os
import re
import sys
import time

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from . import SCHEMA, actions, auth, board, door, net, paths

READ_METHODS = ("GET", "HEAD", "OPTIONS")
DIGITS = re.compile(r"[0-9]{1,12}\Z")      # a length in ASCII digits ("²".isdigit() is true, and int() refuses it)
BODY_MAX = 4096                 # bytes of a request's body; more is refused unread
CONNECTIONS_MAX = 64            # connections at once (uvicorn's limit_concurrency); more get 503
DOOR_EVERY_S = 120              # the door asks root's reader for a reading this often at most
SOURCE = "bromigos_board.source"    # where LocalOnly keeps the request's source address, in its scope
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
    every answer the API's headers. The address is worked out here, once, and kept in the
    request's scope (source_of): nothing later reads the headers for it again. Only HTTP is
    answered: a WebSocket is closed unanswered."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        if scope["type"] != "http":
            with contextlib.suppress(Exception):
                await send({"type": "websocket.close", "code": 1008})
            return None

        async def with_headers(message):
            if message["type"] == "http.response.start":
                have = {k.lower() for k, _ in message.get("headers", [])}
                message["headers"] = list(message.get("headers", [])) + [
                    (k.lower().encode(), v.encode()) for k, v in API_HEADERS.items() if k.lower().encode() not in have]
            await send(message)

        peer = (scope.get("client") or (None,))[0]
        headers = scope.get("headers") or []
        scope[SOURCE] = src = net.source(headers, peer)
        if not net.is_private(src, net.arrived_at(headers)):
            return await error(403, NOT_LOCAL)(scope, receive, with_headers)
        return await self.app(scope, receive, with_headers)


def touch(path):
    """Mark one of the two files root's reader watches (bromigos-board-snapshot.path). It never
    makes the file: tmpfiles did, in a folder that is root's. True when it was marked."""
    try:
        fd = os.open(paths.at(path), os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return False
    try:
        os.utime(fd)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


def touch_wanted():
    """Say a signed-in browser is connected, so the reader reads every 15 seconds while it is."""
    return touch(paths.WANTED)


def ask_for_the_door(state):
    """The door asks for one reading: only when the last is older than DOOR_EVERY_S, and no more
    often than that. Signed out, a device can't keep root's reader running."""
    now = time.monotonic()
    if state.door_asked is not None and now - state.door_asked < DOOR_EVERY_S:
        return False
    with contextlib.suppress(OSError):
        if time.time() - os.stat(paths.at(paths.SNAPSHOT)).st_mtime < DOOR_EVERY_S:
            return False
    state.door_asked = now
    return touch(paths.DOOR)


def read_snapshot():
    doc = paths.read_json(paths.at(paths.SNAPSHOT))
    return doc if isinstance(doc, dict) else None


def session_of(request):
    return auth.session_for(request.cookies.get(auth.COOKIE))


def source_of(request):
    """The request's source address, as LocalOnly worked it out."""
    return request.scope.get(SOURCE) or ""


# said on the door, as it is: the code wasn't checked, so it is still good
BUSY = ("busy", "The server is busy: many codes are being tried at once. Your code wasn't used. Try it again in a moment.")


async def try_code(st, src, check, wrong):
    """One code checked, as every code is (auth.py, "wrong codes"): the try counts for src from
    now (429 when src has made five in a minute), it waits its turn at the gate, it is checked
    (`check`, awaited), and when it was wrong (`wrong(result)`) the next check waits 200 ms more.
    A right code, or one never checked, doesn't count. Returns (result, None), or (None, the
    error answer)."""
    why = st.tries.begin(src)
    if why:
        return None, error(429, ("too-many", why), headers={"Retry-After": "60"})
    try:
        await asyncio.wait_for(st.gate.acquire(), auth.GATE_WAIT_S)
    except asyncio.TimeoutError:
        st.tries.undo(src)
        return None, error(503, BUSY, headers={"Retry-After": "5"})
    try:
        result = await check()
        if wrong(result):
            await st.sleep(auth.WRONG_EVERY_S)          # the gate stays shut a while after a wrong code
        else:
            st.tries.undo(src)
        return result, None
    except BaseException:
        st.tries.undo(src)
        raise
    finally:
        st.gate.release()


def csrf_ok(request):
    """Every request that changes something comes from the board's own page: it carries
    X-Bromigos-Board: 1, which a page on another site can't send without a CORS answer this API
    never gives; it was sent to one of the board's own names (paths.names: <server>.local or
    home-<server>.local), whatever Host says otherwise; its Origin, when the browser sends one, is
    that same name; its Sec-Fetch-Site, when sent, is same-origin; and its body is JSON
    (json_body), which a plain form can't send. The session cookie is SameSite=Strict besides."""
    if request.method in READ_METHODS:
        return True
    if request.headers.get(CSRF_HEADER) != "1":
        return False
    host = request.headers.get("host", "").lower()
    if host not in paths.names():
        return False
    origin = request.headers.get("origin")
    if origin is not None and origin.lower() != f"https://{host}":
        return False
    return request.headers.get("sec-fetch-site", "same-origin") in ("same-origin", "none")


async def json_body(request):
    """(dict, None) or (None, an error response)."""
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        return None, error(415, ("not-json", "Send JSON (Content-Type: application/json)."))
    too_big = error(413, ("too-big", "That request is too big."), headers={"Connection": "close"})
    length = request.headers.get("content-length")
    if length is not None and (not DIGITS.match(length) or int(length) > BODY_MAX):
        return None, too_big                     # refused by what it says of itself, unread
    body = b""
    async for chunk in request.stream():         # and read no further than the limit, whatever it said
        body += chunk
        if len(body) > BODY_MAX:
            return None, too_big
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
    ask_for_the_door(request.app.state)
    return JSONResponse(door.door(read_snapshot()))


async def get_local(request):
    """Nothing but a yes: LocalOnly refused the request already if its address isn't one the
    board answers. Caddy asks this for addresses of the lab's private network (site.caddy)."""
    return Response(status_code=204)


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
    result, refused = await try_code(request.app.state, src, lambda: run_in_threadpool(auth.use_code, doc.get("code")),
                                     lambda r: r is not True)
    if refused:
        return refused
    if result is not True:
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


_jobs_trouble = [None]


def jobs_now(limit=50):
    try:
        A = _activity()
        return A.list_jobs(A.Env(), limit=limit)
    except Exception as e:     # no bromigos-core here, or an unreadable folder: no jobs, not a crash
        why = f"{type(e).__name__}: {e}"
        if why != _jobs_trouble[0]:           # said once in the service's log, not at every look
            _jobs_trouble[0] = why
            print(f"bromigos-board: the activity records can't be read ({why}): the stream has no jobs", file=sys.stderr, flush=True)
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


async def post_actions(request):
    """A fixed verb on a catalogue app (actions.py). The API only writes the request down, in its
    own folder: root's helper finds it there, checks it again, starts the job and leaves its
    answer in root's folder, which the API reads back."""
    rec = session_of(request)
    if not rec:
        return error(401, SIGNED_OUT)
    if not csrf_ok(request):
        return error(403, CSRF)
    doc, bad = await json_body(request)
    if bad:
        return bad
    st = request.app.state
    src = source_of(request)
    deleting = bool(doc.get("delete_data"))

    async def ask_and_wait():
        rid = await run_in_threadpool(actions.ask, doc.get("verb"), doc.get("app"), rec, None,
                                      doc.get("delete_data", False), doc.get("code"))
        if st.after_ask:
            await run_in_threadpool(st.after_ask, rid)      # (the tests' stand-in for the helper's unit)
        return rid, await run_in_threadpool(actions.wait, rid, st.action_wait_s)
    try:
        if deleting:                            # its code is a try, as at sign-in
            got, refused = await try_code(st, src, ask_and_wait, lambda r: bool(r[1]) and r[1].get("code") == "needs-code")
            if refused:
                return refused
            rid, out = got
        else:
            rid, out = await ask_and_wait()
    except actions.Refused as e:
        return error(400, (e.code, e.words))
    except OSError:
        return error(503, ("no-actions", "Actions aren't set up on this server."))
    if out is None:
        return JSONResponse({"schema": SCHEMA, "ok": True, "job": None, "request": rid,
                             "words": "Asked. It shows in Activity when it starts."}, status_code=202)
    if not out.get("ok"):
        code = out.get("code") if out.get("code") in actions.REFUSALS else "bad-request"
        return error(403, (code, actions.REFUSALS[code]))
    return JSONResponse({"schema": SCHEMA, "ok": True, "job": out.get("job"), "request": rid, "words": out.get("words")},
                        status_code=202)


# a job's action that was refused: the job isn't there (404), or isn't in a state for it (409)
JOB_STATUS = {"no-job": 404, "unknown-verb": 404, "ended": 409, "not-asking": 409, "bad-choice": 409, "not-safe": 409,
              "cant-retry": 409, "not-taken": 409}


async def post_job_action(request):
    """A job's own action: answer its question, stop it, or start it again (actions.py). Like an
    app's, the API only writes the request down; root's helper looks the job up among root's own
    records, checks that its state allows the action, and passes it to `bromigos activity`."""
    rec = session_of(request)
    if not rec:
        return error(401, SIGNED_OUT)
    if not csrf_ok(request):
        return error(403, CSRF)
    doc, bad = await json_body(request)
    if bad:
        return bad
    st = request.app.state
    src = source_of(request)
    job, verb = request.path_params["job"], request.path_params["verb"]

    async def ask_and_wait():
        rid = await run_in_threadpool(actions.ask_job, verb, job, rec, None, doc.get("question"), doc.get("choice"),
                                      doc.get("code"))
        if st.after_ask:
            await run_in_threadpool(st.after_ask, rid)      # (the tests' stand-in for the helper's unit)
        return rid, await run_in_threadpool(actions.wait, rid, st.action_wait_s)
    try:
        if doc.get("code") is not None:         # its code is a try, as at sign-in
            got, refused = await try_code(st, src, ask_and_wait,
                                          lambda r: bool(r[1]) and r[1].get("code") == "danger-needs-code")
            if refused:
                return refused
            rid, out = got
        else:
            rid, out = await ask_and_wait()
    except actions.Refused as e:
        return error(JOB_STATUS.get(e.code, 400), (e.code, e.words))
    except OSError:
        return error(503, ("no-actions", "Actions aren't set up on this server."))
    if out is None:
        return JSONResponse({"schema": SCHEMA, "ok": True, "job": None if verb == "retry" else job, "request": rid,
                             "words": "Asked. The job's card shows what became of it."}, status_code=202)
    if not out.get("ok"):
        code = out.get("code") if out.get("code") in actions.REFUSALS else "bad-request"
        return error(JOB_STATUS.get(code, 403), (code, actions.REFUSALS[code]))
    return JSONResponse({"schema": SCHEMA, "ok": True, "job": out.get("job"), "request": rid, "words": out.get("words")},
                        status_code=202)


ROUTES = [
    Route("/api/door", get_door, methods=["GET"]),
    Route("/api/local", get_local, methods=["GET"]),
    Route("/api/session", get_session, methods=["GET"]),
    Route("/api/session", post_session, methods=["POST"]),
    Route("/api/session", delete_session, methods=["DELETE"]),
    Route("/api/session/{sid}", delete_session_id, methods=["DELETE"]),
    Route("/api/board", get_board, methods=["GET"]),
    Route("/api/activity", get_activity, methods=["GET"]),
    Route("/api/actions", post_actions, methods=["POST"]),
    Route("/api/activity/{job}/{verb}", post_job_action, methods=["POST"]),
]


def make_app(tries=None, poll=1.0, stream_s=None, sleep=asyncio.sleep, after_ask=None,
             action_wait_s=actions.RESULT_WAIT_S):
    """The app. `stream_s` ends an activity stream after that many seconds (tests); None: never.
    `sleep` is how a wrong code's answer waits (tests: a stand-in). `after_ask` is called with a
    request's id once it's written (tests: a stand-in for root's helper; on a server systemd's
    path unit starts the helper, and the API calls nothing)."""
    app = Starlette(routes=list(ROUTES))
    app.state.after_ask = after_ask
    app.state.action_wait_s = action_wait_s
    app.state.tries = tries or auth.Tries()
    app.state.gate = asyncio.Lock()             # one code checked at a time (try_code)
    app.state.sleep = sleep
    app.state.door_asked = None
    app.state.poll = poll
    app.state.stream_s = stream_s
    return LocalOnly(app)

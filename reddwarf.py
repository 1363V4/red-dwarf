import asyncio
import json
import mimetypes
import os
import re
import signal
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import inspect
from contextlib import aclosing
from html import escape
from pprint import pprint
from collections import namedtuple


# RESPONSE

Response = namedtuple("Response", ['body', 'status', 'type', 'headers'])

def html(body, status=HTTPStatus.OK, headers=None):
    # why sync and no async? can't remember
    # header None because i'm afraid to [] in kw, but maybe i can
    return Response(body, status, "text/html", list(headers or []))

def empty():
    return Response("", HTTPStatus.NO_CONTENT, None, [])

def cookie(key, value, path="/", max_age=None, secure=True, httponly=True, samesite="Lax"):
    parts = [f"{key}={value}", f"Path={path}"]

    if max_age is not None:
        parts.append(f"Max-Age={max_age}")
    if secure:
        parts.append("Secure")
    if httponly:
        parts.append("HttpOnly")
    if samesite:
        parts.append(f"SameSite={samesite}")

    return ("Set-Cookie", "; ".join(parts))

def patch(data):
    # simplest patch ever
    lines = ["event: datastar-patch-elements"]
    lines += [f"data: elements {line}" for line in data.splitlines()]

    return "\n".join(lines) + "\n\n"

# REQUEST

@dataclass(slots=True)
class Request:
    method: str
    raw_path: str
    path: str
    query: dict
    headers: dict
    body: bytes
    signals: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)


def _read_signals(request):
    # we'll use it when handling requests but i write it here
    if "datastar-request" not in request.headers:
        return {}
    if request.method in ("GET", "DELETE"):
        data = request.query.get("datastar") or ['']
        data = data[0]
    elif request.headers.get("content-type") == "application/json":
        data = request.body.decode("utf-8", errors="replace")
    else:
        return {}
    return json.loads(data) if data else {}

async def _read_request(reader):
    """
    unsure if fit for http2/3 
    """
    line = await reader.readline()
    if not line:
        return None

    parts = line.decode("utf-8", errors="replace").split()
    if len(parts) < 2:
        return None

    method, raw_path = parts[0], parts[1]
    print(f"grug see {method} request on {escape(raw_path)}") # telemetry ftw

    split = urlsplit(raw_path)
    path = split.path or "/"
    query = parse_qs(split.query)
    # i don't see why you'd need more info from the split

    headers = {}
    while True:
        header_line = await reader.readline()
        # Read headers until the blank separator line. (put link to spec)
        if header_line in (b"\r\n", b"\n", b""):
            break

        decoded = header_line.decode("utf-8", errors="replace").strip()
        if ":" not in decoded:
            # Skip malformed header lines instead of crashing.
            continue
        name, value = decoded.split(":", 1)
        headers[name.strip().lower()] = value.strip()

    body = b""
    try:
        content_length = int(headers.get("content-length", 0))
        if content_length > 0:
            body = await reader.readexactly(content_length)
    except ValueError:
        pass

    return Request(method, raw_path, path, query, headers, body)


# ROUTING

_routes = []  # (method, compiled_regex, [param_names], handler_fn)

def _path_to_regex(path):
    # we turn /path/<arg1>/<arg2> into regex capture groups
    names = re.findall(r"\<(\w+)\>", path)
    pattern = re.sub(r"\<(\w+)\>", r"([^/]+)", path)  
    # i see the case for wildcards, like in /path/*
    # but i'd prefer not to write the code
    # and force a /path/<_> workaround
    # match/case style
    return re.compile(f"^{pattern}$"), names

def _add_route(method, path):
    regex, param_names = _path_to_regex(path)

    def decorator(fn):
        _routes.append((method, regex, param_names, fn))
        return fn

    return decorator


def get(path):
    return _add_route("GET", path)


def post(path):
    return _add_route("POST", path)


def put(path):
    return _add_route("PUT", path)


def delete(path):
    return _add_route("DELETE", path)


_before_request = []
_after_response = []


def before_request(fn):
    # only put sync functions in there
    # until i find a reason to async scan
    _before_request.append(fn)
    return fn

def after_response(fn):
    _after_response.append(fn)
    return fn


# APP

async def _send_full(writer, body, status, content_type, headers):
    # here i define every arg, and will unpack Response when calling _send_full
    # should i write _send_full(response) and unpack in it?
    # guido take the wheel
    header = (
        f"HTTP/1.1 {status.value} {status.phrase}\r\n"
        f"Content-Length: {len(body)}\r\n"
    )
    if content_type:
        header += f"Content-Type: {content_type}\r\n"
    for key, value in headers:
        header += f"{key}: {value}\r\n"
    header += "\r\n"

    # we send static assets as bytes
    # maybe i could make two function instead of checking for encoding, like _send_full_static/_send_full_file
    # will have to test if it speeds boost
    # ... if we talk performance, just put uvloop bro
    # asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    if not isinstance(body, bytes):
        body = body.encode("utf-8")    

    writer.write(header.encode("utf-8") + body)
    await writer.drain()

async def _send_sse_headers(writer, headers=None):
    header = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/event-stream\r\n"
        "Cache-Control: no-cache\r\n"
        "Connection: keep-alive\r\n"
    )

    for k, v in headers or []:
        header += f"{k}: {v}\r\n"
    header += "\r\n" # nécessaire ?

    writer.write(header.encode("utf-8"))
    await writer.drain()

async def _send_sse_event(writer, event):
    writer.write(event.encode("utf-8"))
    await writer.drain()

# APP

def _find_handler(method, path):
    # walk routes in order, return first match
    # so register carefully
 
    for route_method, regex, param_names, fn in _routes:
        if route_method != method:
            continue
        m = regex.match(path)
        if m:
            params = dict(zip(param_names, m.groups()))  # {"id": "42", ...}
            return fn, params
    return None, {}

async def _serve(host, port, sock):
    async def handle(reader, writer):
        try:
            request = await _read_request(reader)
            if request is None:
                await _send_full(writer, "grug not understand request", HTTPStatus.BAD_REQUEST, "text/plain", [])
                return

            handler, params = _find_handler(request.method, request.path)
            request.params = params
            request.signals = _read_signals(request)

            if handler is None:  # unregistered route, try static and if not conclusive, return 500
                candidate = Path("static") / request.path.removeprefix("/static/")
                candidate = candidate.resolve()
                if (
                    request.method == "GET"
                    and candidate.is_relative_to(Path("static").resolve())
                    and candidate.is_file()
                ):
                    # check if it's a cached asset
                    stat = candidate.stat()
                    etag = f'"{hex(int(stat.st_mtime * 1000))[2:]}{hex(stat.st_size)[2:]}"'
                    if request.headers.get("if-none-match") == etag:
                        await _send_full(
                            writer,
                            "",
                            HTTPStatus.NOT_MODIFIED,
                            None,
                            [("ETag", etag)],
                        )
                    else:
                        mime, _ = mimetypes.guess_type(candidate.name)
                        print(candidate, mime)
                        body = candidate.read_bytes()
                        await _send_full(
                            writer,
                            body,
                            HTTPStatus.OK,
                            mime or 'application/octet-stream',
                            [("ETag", etag)],
                        )
                else:
                    await _send_full(
                        writer,
                        "grug not know this path",
                        HTTPStatus.NOT_FOUND,
                        "text/plain",
                        [],
                    )
                return

            for fn in _before_request:
                early_response = fn(request)
                if early_response is not None:
                    await _send_full(writer, *early_response)
                    return

            response = handler(request)

            if inspect.isasyncgen(response): # sse patch
                try:
                    async with aclosing(response) as gen:
                        await _send_sse_headers(writer)
                        async for event in gen:
                            await _send_sse_event(writer, event)
                except (
                    asyncio.CancelledError,
                    BrokenPipeError,
                    ConnectionResetError,
                    ConnectionAbortedError,
                ):
                    pass
            else:
                response = await response
                for fn in _after_response:
                    response = fn(request, response)
                await _send_full(writer, *response)

        except Exception as e:
            print(f"grug had problem: {e}")
            traceback.print_exc()
            await _send_full(
                writer,
                "grug make accident",
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "text/plain",
                [],
            )

        finally:
            writer.close()
            await writer.wait_closed()

    # Bind either to a Unix domain socket or a TCP host/port.
    if sock:
        if os.name == "nt":
            raise OSError(
                "grug on windows — unix socket not available, use host+port instead"
            )
        if os.path.exists(sock):
            # Remove stale socket file left by previous unclean shutdown.
            os.unlink(sock)
        server = await asyncio.start_unix_server(handle, path=sock)
        os.chmod(sock, 0o660)
        print(f"grug listen on unix:{sock}")
    else:
        server = await asyncio.start_server(handle, host, port)
        # maybe a welcome message: 1 read the tao, 2 escape user input
        print(f"grug listen on http://{host}:{port}")

    # SIGTERM is common in containers/process managers.
    # Closing the server lets `serve_forever()` exit cleanly.
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: server.close())

    async with server:
        await server.serve_forever()

def run(host="127.0.0.1", port=8080, sock=None, reload=False):
    if reload:
        def watch_and_restart():
            mtimes = {}

            def iter_watched_files():
                yield from Path.cwd().glob("*.py")
                yield from Path("static").glob("**/*")

            while True:
                for file_path in iter_watched_files():
                    try:
                        mtime = file_path.stat().st_mtime
                    except OSError:
                        continue
                    key = str(file_path.resolve())
                    if key not in mtimes:
                        mtimes[key] = mtime
                    elif mtime > mtimes[key]:
                        print(f"grug see change in {file_path}, restarting...")
                        # argv not used at the moment
                        os.execv(sys.executable, [sys.executable] + sys.argv)
                time.sleep(1)

        t = threading.Thread(target=watch_and_restart, daemon=True)
        t.start()
    try:
        asyncio.run(_serve(host, port, sock))
    except KeyboardInterrupt:
        print("grug: out.")

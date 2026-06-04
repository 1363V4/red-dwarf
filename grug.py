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


# RESPONSE

def html(body, status=HTTPStatus.OK, headers=None):
    # why sync and no async? can't remember
    # header None because i'm afraid to [] in kw, but maybe i can
    return (body, status, "text/html", headers or [])

def empty():
    return "", HTTPStatus.NO_CONTENT, None, []

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
    print(f"grug see {method} request on {raw_path}") # telemetry ftw

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

def _add(method, path):
    regex, param_names = _path_to_regex(path)

    def decorator(fn):
        _routes.append((method, regex, param_names, fn))
        return fn

    return decorator

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


def get(path):
    return _add("GET", path)


def post(path):
    return _add("POST", path)


def put(path):
    return _add("PUT", path)


def delete(path):
    return _add("DELETE", path)

# APP

async def _send_full(writer, body, status, content_type, headers):
    # head and body for html, empty or error responses
    header = (
        f"HTTP/1.1 {status.value} {status.phrase}\r\n"
        f"Content-Length: {len(body)}\r\n"
    )
    if content_type:
        header += f"Content-Type: {content_type}\r\n"
    for key, value in headers:
        header += f"{key}: {value}\r\n"
    header += "\r\n"

    # maybe i could make two function instead of checking for encoding
    # will have to test if it speeds boost
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

            if handler is None:  # unknown route, try static and if not conclusive, return 500
                candidate = Path("static") / request.path.removeprefix("/static/")
                candidate = candidate.resolve()
                if (
                    request.method == "GET"
                    and candidate.is_relative_to(Path("static").resolve())
                    and candidate.is_file()
                ):
                    mime, _ = mimetypes.guess_type(candidate.name)
                    body = candidate.read_bytes()
                    await _send_full(
                        writer,
                        body,
                        HTTPStatus.OK,
                        mime or 'application/octet-stream',
                        [],
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

            response = handler(request)

            if inspect.isasyncgen(response):
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

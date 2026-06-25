import asyncio
import inspect
import json
import logging
import mimetypes
import multiprocessing
import os
import re
import signal
import time
import traceback
from collections import namedtuple
from contextlib import aclosing
from dataclasses import dataclass, field
from html import escape
from http import HTTPStatus
from http.cookies import SimpleCookie
from pathlib import Path
from pprint import pprint
from urllib.parse import parse_qs, urlsplit

# Hello and welcome!
# This code is intended to be read by humans.
# What is a server?
# a miserable little pile of routes.
# that is, functions which map requests to html responses
# and this is all we'll do.

Route = namedtuple("Route", ["method", "regex", "param_names", "handler"])
_routes = []  # BEHOLD THE STATE


@dataclass(slots=True)
class Request:
    method: str
    raw_path: str
    path: str
    query: dict
    headers: dict
    body: bytes
    signals: dict
    cookies: dict
    # Now I know what you are going to say
    # "But cookies are included in headers!"
    # Yes. But we design for convenience,
    # sometimes that means redundancy,
    # or straying from the spec.
    # For the same reason,
    # we're adding a cookie arg to Response.
    params: dict = field(default_factory=dict)
    # params is the only parameter we can't infer from the Request content
    # because we have to wait for the server to match queried path
    # against registered routes.
    # Hence the default_factory


# @dataclass(slots=True)
# class Response:
#     body: str
#     status: str
#     content_type: str
#     headers: dict = field(default_factory=dict)
#nah tuple better for unpacking

Response = namedtuple(
    "Response", ["body", "status", "content_type", "headers"]
)

# And finally some control flow,
# functions to call before parsing a request
# or after sending a response
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


# SECURITY

MAX_BODY_SIZE = 1_048_576  # bytes
MAX_HEADER_LINE = 8192  # bytes
READ_TIMEOUT = 10  # s

# ROUTES


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


# REQUESTS


def _read_signals(headers, method, query, body):
    # Datastar specific
    if "datastar-request" not in headers:
        return {}
    if method in ("GET", "DELETE"):
        data = query.get("datastar") or [""]
        data = data[0]
    elif headers.get("content-type") == "application/json":
        data = body.decode("utf-8", errors="replace")
    else:
        return {}
    return json.loads(data) if data else {}


async def _read_request(reader):
    """
    unsure if fit for http2/3
    should be called _parse_request? but there's a read timeout
    """
    try:
        async with asyncio.timeout(READ_TIMEOUT):
            line = await reader.readline()
    except TimeoutError:
        return None

    if not line:
        return None

    parts = line.decode("utf-8", errors="replace").split()
    if len(parts) < 2:
        return None

    method, raw_path = parts[0], parts[1]
    print(f"grug see {method} request on {escape(raw_path)}")  # telemetry ftw

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
        if len(header_line) > MAX_HEADER_LINE:
            return None
        decoded = header_line.decode("utf-8", errors="replace").strip()
        if ":" not in decoded:
            # Skip malformed header lines instead of crashing.
            continue
        name, value = decoded.split(":", 1)
        headers[name.strip().lower()] = (
            value.strip()
        )  # headers are overwritten because we don't like shenanigans

    cookies = {}
    if cookie := headers.get('cookie'):
        try:
            c = SimpleCookie(cookie)
            for key, morsel in c.items():
                cookies[key] = morsel.value
        except Exception as e:
            pass

    body = b""
    try:
        content_length = int(headers.get("content-length", 0))
        if 0 < content_length < MAX_BODY_SIZE:
            body = await reader.readexactly(content_length)
    except ValueError:
        pass

    signals = _read_signals(headers, method, query, body)

    return Request(method, raw_path, path, query, headers, body, signals, cookies)


# USER RESPONSES


def html(body, headers=None, cookies=None):
    # why sync and no async? can't remember
    if cookies:
        c = SimpleCookie()
        for key, value in cookies.items():
            c[key] = value
            c[key]["path"] = "/"
            c[key]["max-age"] = None
            c[key]["secure"] = True
            c[key]["httponly"] = True
            c[key]["samesite"] = "Lax"
    if not headers:
        headers = []
    headers += [c]
    return Response(body, HTTPStatus.OK, "text/html", headers)


def empty():
    return Response("", HTTPStatus.NO_CONTENT, None, [])


def patch(data):
    # simplest patch ever
    lines = ["event: datastar-patch-elements"]
    lines += [f"data: elements {line}" for line in data.splitlines()]

    return "\n".join(lines) + "\n\n"


# WRITERS


async def _send_full(writer, response):
    body, status, content_type, headers = response
    header_buffer = [
        f"HTTP/1.1 {status.value} {status.phrase}",
        f"Content-Length: {len(body)}",
    ]
    if content_type:
        header_buffer += [f"Content-Type: {content_type}"]
    for header in headers:
        header_buffer += [f"{header}"]
    header = "\r\n".join(header_buffer)
    header += "\r\n\r\n"

    # ... if we talk performance, just put uvloop bro
    # asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    if not isinstance(body, bytes):
        body = body.encode("utf-8")

    writer.write(header.encode("utf-8") + body)
    await writer.drain()


async def _send_sse_headers(writer):
    header_buffer = [
        "HTTP/1.1 200 OK",
        "Content-Type: text/event-stream",
        "Cache-Control: no-cache",
        "Connection: keep-alive",
    ]

    header = "\r\n".join(header_buffer)
    header += "\r\n\r\n"
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

async def _handle(reader, writer):
    # this is a callback after the connection has been initialized
    # reader is a StreamReader object, 
    # writer is a StreamWriter object.
    # this is where everything happens:
    # we read from the stream, parse it into a "request"
    # find its "route" and write stuff

    try:
        request = await _read_request(reader)
        if request is None:
            await _send_full(
                writer,
                Response(
                    "Bad Request", HTTPStatus.BAD_REQUEST, "text/plain", []
                ),
            )
            return

        handler, params = _find_handler(request.method, request.path)
        request.params = params

        for fn in _before_request:
            early_response = fn(request)
            if early_response is not None:
                await _send_full(writer, early_response)
                return

        if handler is None:
            # unregistered route, try static and if not conclusive, return 500
            candidate = Path("static") / request.path.removeprefix("/static/")
            candidate = candidate.resolve()
            if (
                request.method == "GET"
                and candidate.is_relative_to(Path("static").resolve())
                and candidate.is_file()
            ):
                # check if it's a cached asset
                stat = candidate.stat()
                etag = (
                    f'"{hex(int(stat.st_mtime * 1000))[2:]}{hex(stat.st_size)[2:]}"'
                )
                if request.headers.get("if-none-match") == etag:
                    await _send_full(
                        writer,
                        Response(
                            "", HTTPStatus.NOT_MODIFIED, None, [("ETag", etag)]
                        ),
                    )
                else:
                    mime, _ = mimetypes.guess_type(candidate.name)
                    body = candidate.read_bytes()
                    await _send_full(
                        writer,
                        Response(
                            body,
                            HTTPStatus.OK,
                            mime or "application/octet-stream",
                            [("ETag", etag)],
                        ),
                    )
            else:
                await _send_full(
                    writer,
                    Response(
                        "Not Found", HTTPStatus.NOT_FOUND, "text/plain", []
                    ),
                )
            return

        response = handler(request)

        if inspect.isasyncgen(response):  # sse patch
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
            await _send_full(writer, response)

    except Exception as e:
        print(f"grug had problem: {e}")
        traceback.print_exc()
        await _send_full(
            writer,
            Response(
                "Server Error",
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "text/plain",
                [],
            ),
        )

    finally:
        writer.close()
        await writer.wait_closed()


async def _serve(host, port, sock):
    # Bind either to a Unix domain socket or a TCP host/port.
    if sock:
        if os.name == "nt":
            raise OSError(
                "grug on windows — unix socket not available, use host+port instead"
            )
        if os.path.exists(sock):
            # Remove stale socket file left by previous unclean shutdown.
            os.unlink(sock)
        server = await asyncio.start_unix_server(_handle, path=sock)
        os.chmod(sock, 0o660)
        print(f"grug listen on unix:{sock}")
    else:
        server = await asyncio.start_server(_handle, host, port)
        # maybe a welcome message: 1 read the tao, 2 escape user input
        print(f"grug listen on http://{host}:{port}")

    # SIGTERM is common in containers/process managers.
    # Closing the server lets `serve_forever()` exit cleanly.
    # but shouldn't this be higher level?
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: server.close())

    async with server:
        await server.serve_forever()


def _watch_for_changes():
    def iter_watched_files():
        yield from Path.cwd().glob("*.py")
        yield from Path("static").glob("**/*")
        yield from Path.cwd().glob("reddwarf/*.py") # REMEMBER TO REMOVE THAT

    mtimes = {}

    while True:
        time.sleep(1)  # os.wait() instead? maybe
        for file_path in iter_watched_files():
            try:
                mtime = file_path.stat().st_mtime
            except OSError:
                continue
            key = str(file_path.resolve())
            if key not in mtimes:
                mtimes[key] = mtime
            elif mtime > mtimes[key]:
                return file_path


def _run_once(host, port, sock):
    # separate function so Windows can pickle it
    # used in reload mode, see comments there
    try:
        asyncio.run(_serve(host, port, sock))
    except KeyboardInterrupt:
        pass


def run(host="127.0.0.1", port=8080, sock=None, reload=False):
    try:
        if reload:
            # reload works like this:
            # we spawn a child process to serve
            # on file change (blocking in parent process)
            # we restart child
            # pros: clean memory reset
            # cons: not pure asyncio
            # man i suck
            while True:
                child = multiprocessing.Process(
                    target=_run_once, args=(host, port, sock)
                )
                child.start()

                changed = _watch_for_changes()
                print(f"grug see change in {changed}, restarting...")

                child.terminate()
                child.join()
        else:
            asyncio.run(_serve(host, port, sock))
    except KeyboardInterrupt:
        print("grug: out.")

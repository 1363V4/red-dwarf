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
from collections import namedtuple
from contextlib import aclosing
from dataclasses import dataclass, field
from html import escape
from http import HTTPStatus
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

# Hello and welcome!
# This code is intended to be read by humans.
# ---
# "What is a server?
# A miserable little pile of routes."
# server = functions mapping requests to html responses
# and this is all we'll do.

_routes = []  # BEHOLD: ALL THE STATE WE NEED!
# and a route is this:
# an HTTP method, a regex strings, the parameters we want to get back, and the fn to call
Route = namedtuple("Route", ["method", "regex", "param_names", "handler"])


# Next we'll use a dataclass to parse requests.


@dataclass(slots=True)
class Request:
    method: str
    raw_path: str
    path: str
    version: str
    query: dict
    headers: dict
    body: bytes
    signals: dict
    cookies: dict
    params: dict = field(default_factory=dict)


# cookies: request.cookies is here for convenience, since they're already in request.headers
# params: we have to wait for the server to match queried path against registered routes.
#  		  This is why we use a default factory here.
# PS: Adam said we could use @property for stuff like body, params...

Response = namedtuple("Response", ["body", "status", "content_type", "headers"])

# Middleware:
# From now, I only consider before request
# A generic @on_response feels like a code smell to me
# especially since by design we rely on Caddy
# but I'm open to debate
_before_request = []

_STATIC_DIR = Path.cwd() / "static"


def before_request(fn):
    # only put sync functions in there
    # until i find a reason to async scan
    _before_request.append(fn)
    return fn


# SECURITY

MAX_BODY_SIZE = 1_048_576  # bytes
MAX_HEADER_LINE = 8_192  # bytes
REQUEST_TIMEOUT = 10  # s
KEEPALIVE_TIMEOUT = 150  # s
# Has to be more than Caddy's 120s timeout
MAX_REQUESTS_PER_CONNECTION = 1000

# LOGGING

logger = logging.getLogger(__name__)

# ROUTES


def _path_to_regex(path):
    # we turn /path/<arg1>/<arg2> into regex capture groups
    names = re.findall(r"\<(\w+)\>", path)
    pattern = re.sub(r"\<(\w+)\>", r"([^/]+)", path)
    # i see the case for wildcards, like in /path/*
    # but i'd prefer not to write the code
    # and force users into a /path/<_> workaround
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


async def _read_request(reader, timeout):
    """
    unsure if fit for http2/3
    should be called _parse_request? but there's a read timeout
    """
    try:
        async with asyncio.timeout(timeout):
            line = await reader.readline()

            if not line:
                return None

            parts = line.decode("utf-8", errors="replace").split()
            # maybe use surrogateescape instead?
            if len(parts) < 2:
                return None

            method, raw_path = parts[0], parts[1]
            version = parts[2] if len(parts) > 2 else "HTTP/1.0"
            logger.info(f"{method} request on {escape(raw_path)}")  # telemetry ftw

            split = urlsplit(raw_path)
            path = split.path or "/"
            query = parse_qs(split.query)
            # i don't see why you'd need more info from the split

            headers = {}
            while True:
                header_line = await reader.readline()
                # We read headers until the blank separator line.
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

            if "chunked" in headers.get("transfer-encoding", "").lower():
                return None  # yeah, we don't do that here...

            cookies = {}
            if cookie := headers.get("cookie"):
                try:
                    c = SimpleCookie(cookie)
                    for key, morsel in c.items():
                        cookies[key] = morsel.value
                except Exception:
                    pass

            body = b""
            try:
                content_length = int(headers.get("content-length", 0))
                if 0 < content_length < MAX_BODY_SIZE:
                    body = await reader.readexactly(content_length)
            except ValueError:
                return None

            signals = _read_signals(headers, method, query, body)

    except TimeoutError:
        return None

    return Request(
        method, raw_path, path, version, query, headers, body, signals, cookies
    )


# USER RESPONSES


def html(body, headers=None, cookies=None):
    # why sync and no async? can't remember
    if not headers:
        headers = []
    if cookies:
        c = SimpleCookie()
        for key, value in cookies.items():
            c[key] = value
            c[key]["path"] = "/"
            c[key]["max-age"] = None
            c[key]["secure"] = True
            c[key]["httponly"] = True
            c[key]["samesite"] = "Lax"
        headers += [c]
    return Response(body, HTTPStatus.OK, "text/html", headers)


def empty():
    return Response("", HTTPStatus.NO_CONTENT, None, [])


def patch(data):
    # simplest patch ever
    lines = ["event: datastar-patch-elements"]
    lines += [f"data: elements {line}" for line in data.splitlines()]

    return "\n".join(lines) + "\n\n"


def redirect(location):
    return Response("", HTTPStatus.TEMPORARY_REDIRECT, None, [f"Location: {location}"])


# WRITERS


async def _send_full(writer, response, connection=None):
    body, status, content_type, headers = response
    # ok... here we unpack
    # because namedtuple is not mutable...
    # so... maybe use a dataclass you dumb dumb?
    if not isinstance(body, bytes):
        body = body.encode("utf-8")
    header_buffer = [
        f"HTTP/1.1 {status.value} {status.phrase}",
        f"Content-Length: {len(body)}",
    ]
    if content_type:
        header_buffer += [f"Content-Type: {content_type}"]
    if connection:
        header_buffer += [f"Connection: {connection}"]
    for header in headers:
        header_buffer += [f"{header}"]
    header = "\r\n".join(header_buffer)
    header += "\r\n\r\n"
    header = header.encode("utf-8")

    writer.write(header + body)
    await writer.drain()


async def _send_server_error(writer):
    await _send_full(
        writer,
        Response("Server Error", HTTPStatus.INTERNAL_SERVER_ERROR, "text/plain", []),
        connection="close",
    )


async def _send_sse_headers(writer):
    header_buffer = [
        "HTTP/1.1 200 OK",
        "Content-Type: text/event-stream",
        "Cache-Control: no-cache",
        # "Connection: keep-alive", I have to check with the discord on that one
        "Connection: close",
    ]

    header = "\r\n".join(header_buffer)
    header += "\r\n\r\n"
    writer.write(header.encode("utf-8"))
    await writer.drain()


async def _send_sse_event(writer, event):
    writer.write(event.encode("utf-8"))
    await writer.drain()


# SERVER


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


# 3 little helpers before te real work begins


def _serve_static(request):
    candidate = _STATIC_DIR / request.path.removeprefix("/static/")
    candidate = candidate.resolve()

    if not (candidate.is_relative_to(_STATIC_DIR) and candidate.is_file()):
        return Response("Not Found", HTTPStatus.NOT_FOUND, "text/plain", [])

    stat = candidate.stat()
    etag = f'"{hex(int(stat.st_mtime * 1000))[2:]}{hex(stat.st_size)[2:]}"'

    if request.headers.get("if-none-match") == etag:
        return Response("", HTTPStatus.NOT_MODIFIED, None, [f"ETag: {etag}"])

    mime, _ = mimetypes.guess_type(candidate.name)
    # Fallback MIME types, maybe i'm missing some
    mime = mime or {
        ".css": "text/css",
        ".js": "application/javascript",
        ".svg": "image/svg+xml",
        ".png": "image/png",
    }.get(candidate.suffix.lower(), "application/octet-stream")

    body = candidate.read_bytes()
    return Response(body, HTTPStatus.OK, mime, [f"ETag: {etag}"])


def _should_keep_alive(request):
    connection = request.headers.get("connection", "").lower()
    if connection == "close":
        return False
    if connection == "keep-alive":
        return True
    # No explicit header: HTTP/1.1 defaults to keep-alive, HTTP/1.0 to close.
    return request.version == "HTTP/1.1"


async def _stream_sse(writer, gen):
    try:
        async with aclosing(gen) as stream:
            await _send_sse_headers(writer)
            async for event in stream:
                await _send_sse_event(writer, event)
    except (
        asyncio.CancelledError,
        BrokenPipeError,
        ConnectionResetError,
        ConnectionAbortedError,
    ):
        pass


async def _handle(reader, writer):
    # this is a callback after the connection has been initialized
    # reader is a StreamReader object,
    # writer is a StreamWriter object.
    # this is where everything happens:
    # we read from the stream, parse it into a "request"
    # find its "route" and write stuff. done.

    keep_alive = True
    requests_served = 0

    try:
        while keep_alive:
            timeout = REQUEST_TIMEOUT if requests_served == 0 else KEEPALIVE_TIMEOUT
            request = await _read_request(reader, timeout)
            if request is None:
                await _send_full(
                    writer,
                    Response("Bad Request", HTTPStatus.BAD_REQUEST, "text/plain", []),
                    connection="close",
                )
                return

            keep_alive = (
                _should_keep_alive(request)
                and requests_served < MAX_REQUESTS_PER_CONNECTION
            )
            connection = "keep-alive" if keep_alive else "close"

            if request.method == "GET" and request.path.startswith("/static/"):
                response = _serve_static(request)
            else:
                handler, params = _find_handler(request.method, request.path)
                request.params = params

                response = None
                for fn in _before_request:
                    response = fn(request)
                    if response is not None:
                        break

                if response is None:
                    if handler is None:
                        response = Response(
                            "Not Found", HTTPStatus.NOT_FOUND, "text/plain", []
                        )
                    else:
                        response = handler(request)

                        if inspect.isasyncgen(response):  # sse patch
                            await _stream_sse(writer, response)
                            return  # if i do indeed close

                        else:
                            response = await response

            await _send_full(writer, response, connection=connection)
            requests_served += 1

    except Exception as e:
        logger.exception("Error handling request.")
        await _send_server_error(writer)

    finally:
        writer.close()
        await writer.wait_closed()


async def _serve(host, port, sock):
    # Bind either to a Unix domain socket or a TCP host/port.
    if sock:
        if os.name == "nt":
            raise OSError(
                "Are you on Windows? — unix socket not available, use host+port instead"
            )
        if os.path.exists(sock):
            # Remove stale socket file left by previous unclean shutdown...
            # does this really matter?
            os.unlink(sock)
        server = await asyncio.start_unix_server(_handle, path=sock)
        # user and group can read and write
        os.chmod(sock, 0o660)
        logger.info(f"Listening on socket:{sock}")
    else:
        server = await asyncio.start_server(_handle, host, port)
        logger.info(f"Listening on http://{host}:{port}")

    # this can be simplified if i only handle sigterm only on linux
    if hasattr(signal, "SIGTERM"):
        try:
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGTERM, server.close)
        except NotImplementedError:
            signal.signal(signal.SIGTERM, lambda *_: server.close())

    async with server:
        try:
            await server.serve_forever()
        except asyncio.CancelledError:  # expected on shutdown
            pass


# APP


def _watch_for_changes():
    def iter_watched_files():
        root = Path.cwd().parent
        # just for this repo, should change it before release
        package = root / "src" / "red_dwarf"
        site = root / "site"
        if package.is_dir():
            yield from package.rglob("*.py")
        if site.is_dir():
            yield from site.rglob("*.py")
            static = site / "static"
            if static.is_dir():
                yield from static.rglob("*")
        yield from root.glob("*.py")

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
                return file_path.name


def _run_once(host, port, sock):
    # separate function so Windows can pickle it.
    # used in reload mode, see comments there
    try:
        asyncio.run(_serve(host, port, sock))
    except KeyboardInterrupt:
        pass


def run(host="127.0.0.1", port=8080, sock=None, reload=False):
    logger.info("Hello and welcome!")
    logger.info("Thank you for using Red Dwarf.")
    logger.info("Here are some recommendations to start:")
    logger.info("1. Read the Tao of Datastar")
    logger.info("2. Remember to escape user input")
    logger.info("3. ???")
    logger.info("4. Profit!")
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
                logger.info("Change detected in %s, restarting...", changed)

                child.terminate()
                child.join()
        else:
            asyncio.run(_serve(host, port, sock))
    except KeyboardInterrupt:
        logger.info("Server shutdown.")


# ... if we talk performance, just put uvloop bro
# asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

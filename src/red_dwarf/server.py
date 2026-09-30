"""The server: matching a Request to a handler, running it, and juggling
connections.

If you're looking for the public interface (rd.get, rd.html, rd.run...),
that's in red_dwarf.py.
"""

import asyncio
import inspect
import logging
import mimetypes
import os
import re
import signal
import stat
from collections import namedtuple
from contextlib import aclosing
from http import HTTPStatus
from pathlib import Path

from .wire import (
    Response,
    _read_request,
    _send_full,
    _send_server_error,
    _send_sse_event,
    _send_sse_headers,
)

_routes = []
# and a route is this:
# (HTTP method, a regex string, the parameters we want to get back, and the fn to call)
Route = namedtuple("Route", ["method", "regex", "param_names", "handler"])

_before_request = []

_STATIC_DIR = Path.cwd() / "static"

# SECURITY

REQUEST_TIMEOUT = 10  # s
KEEPALIVE_TIMEOUT = 150  # s, has to be more than Caddy's 120s timeout
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
        _routes.append(Route(method, regex, param_names, fn))
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


# Middleware:
# From now, I only consider before request
# A generic @on_response feels like a code smell to me
# especially since by design we rely on Caddy
# but I'm open to debate
def before_request(fn):
    # only put sync functions in there
    # until i find a reason to async scan
    _before_request.append(fn)
    return fn


# ROUTING


async def _not_found(request):
    return Response("Not Found", HTTPStatus.NOT_FOUND, "text/plain", [])


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


# STATIC FILES

for _ext, _type in {
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".css": "text/css",
        ".svg": "image/svg+xml",
    }.items():
    mimetypes.add_type(_type, _ext)


def _serve_static(request):
    candidate = _STATIC_DIR / request.path.removeprefix("/static/")
    candidate = candidate.resolve()

    if not (candidate.is_relative_to(_STATIC_DIR) and candidate.is_file()):
        return Response("Not Found", HTTPStatus.NOT_FOUND, "text/plain", [])

    stat = candidate.stat()
    etag = f'"{hex(int(stat.st_mtime * 1000))[2:]}{hex(stat.st_size)[2:]}"'

    if request.headers.get("if-none-match") == etag:
        return Response("", HTTPStatus.NOT_MODIFIED, None, [f"ETag: {etag}"])

    mime = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"

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

# Here we go

async def _handle(reader, writer):
    # _handle is a callback after the connection has been initialized
    # reader is a StreamReader object,
    # writer is a StreamWriter object,
    # both passed by the connection.
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

    except Exception:
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
                "Are you on Windows? Use host+port instead"
            )
        if os.path.exists(sock) and stat.S_ISSOCK(os.stat(sock).st_mode):
            # Remove a stale socket file left by a previous unclean shutdown.
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
        except asyncio.CancelledError:  # server.close() cancels this
            pass

# Red Dwarf
# ---------
# Version: 1.0
# Author: Louis Sunshine
# Permalink: https://github.com/1363V4/red-dwarf
# Website: https://red.leg.ovh/
# Requirements: Python 3.11+
#
# ----------------------------------
#          What is a server?
# A miserable little pile of routes.
# ----------------------------------
#
# Hello and welcome!
# This code is intended to be read by humans.
#
# Red Dwarf is a server.
# Server = "f(request) -> HTML responses",
# and this is all we'll do.

import asyncio
import inspect
import json
import logging
import mimetypes
import os
import re
import signal
import subprocess
import sys
import time
from collections import namedtuple
from contextlib import aclosing, suppress
from dataclasses import dataclass, field
from html import escape
from http import HTTPStatus
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, unquote

logger = logging.getLogger(__name__)

# ROUTES

_routes = []
Route = namedtuple("Route", ["method", "regex", "param_names", "handler"])


def _path_to_regex(path):
    param_names = re.findall(r"<(\w+)>", path)
    pattern = re.sub(r"<(\w+)>", r"([^/]+)", re.escape(path))
    # for wildcards, use the "/path/<_>" workaround
    return re.compile(pattern), param_names


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


def _find_handler(method, path):
    for route_method, regex, param_names, fn in _routes:
        if route_method == method and (m := regex.fullmatch(path)):
            params = dict(zip(param_names, m.groups()))  # {"id": "42", ...}
            return fn, params
    return None, {}


_before_request = []


def before_request(fn):
    _before_request.append(fn)
    return fn


# REQUESTS


@dataclass(slots=True)
class Request:
    method: str
    raw_path: str
    path: str
    version: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    body: bytes
    signals: dict
    cookies: dict[str, str]
    params: dict[str, str] = field(default_factory=dict)


def _read_signals(headers, method, query, body):
    # Datastar specific
    if "datastar-request" not in headers:
        return {}
    if method in ("GET", "DELETE"):
        data = (query.get("datastar") or [""])[0]
    else:
        content_type = headers.get("content-type", "")
        if content_type.split(";")[0] != "application/json":
            return {}
        data = body
    try:
        parsed = json.loads(data) if data else {}
    except (ValueError, TypeError, RecursionError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


REQUEST_TIMEOUT = 10  # s
MAX_BODY_SIZE = 1_048_576  # bytes
MAX_HEADERS = 100

_REQUEST_LINE = re.compile(rb"([A-Z]+) (/[\x21-\x7e\x80-\xff]*) (HTTP/1\.[01])\r\n")
_HEADER_LINE = re.compile(rb"([!#$%&'*+.^_`|~\w-]+):[ \t]*([^\x00\r\n]*?)[ \t]*\r\n")
_FORBIDDEN = re.compile(r"[\x00-\x1f\x7f]")


async def _read_request(reader):
    async with asyncio.timeout(REQUEST_TIMEOUT):
        line = await reader.readline()

        if not line:
            return None
        if not (m := _REQUEST_LINE.fullmatch(line)):
            raise ValueError

        method, target, version = (group.decode() for group in m.groups())

        raw_path, _, qs = target.partition("?")
        path = unquote(raw_path, errors="strict")
        if _FORBIDDEN.search(path):
            raise ValueError
        query = parse_qs(qs)
        logger.info(f"Received {method} request on {escape(path)}")  # telemetry ftw

        headers = {}
        while (header_line := await reader.readline()) != b"\r\n":
            if len(headers) >= MAX_HEADERS:
                raise ValueError
            if not (m := _HEADER_LINE.fullmatch(header_line)):
                raise ValueError

            name = m[1].decode().lower()
            if name in headers or name == "transfer-encoding":
                raise ValueError
            value = m[2].decode(errors="replace")
            headers[name] = value

        cookies = {
            k: v.value for k, v in SimpleCookie(headers.get("cookie", "")).items()
        }

        content_length = headers.get("content-length", "0")
        if not (content_length.isascii() and content_length.isdigit()):
            raise ValueError
        content_length = int(content_length)
        if content_length > MAX_BODY_SIZE:
            raise ValueError
        body = await reader.readexactly(content_length)

    signals = _read_signals(headers, method, query, body)

    return Request(
        method, raw_path, path, version, query, headers, body, signals, cookies
    )


def _should_keep_alive(request):
    return (
        request.version == "HTTP/1.1"
        and "close" not in request.headers.get("connection", "").lower()
    )


# RESPONSES


@dataclass(slots=True)
class Response:
    body: str | bytes
    status: HTTPStatus
    content_type: str | None
    headers: dict[str, str]
    cookies: list[str] = field(default_factory=list)


def _we_got_cookies(cookies):
    cookie_jar = SimpleCookie(cookies)
    for morsel in cookie_jar.values():
        morsel.update(
            [
                ("path", "/"),
                ("secure", "True"),
                ("httponly", "True"),
                ("samesite", "Lax"),
            ]
        )
    return [morsel.OutputString() for morsel in cookie_jar.values()]

    # morsel.update(
    #     {
    #         'path': "/",
    #         'secure': True,
    #         'httponly': True,
    #         'samesite': "Lax",
    #     }
    # )


def html(body, headers=None, cookies=None):
    return Response(
        body,
        HTTPStatus.OK,
        "text/html",
        dict(headers or {}),
        _we_got_cookies(cookies or {}),
    )


def empty():
    return Response("", HTTPStatus.NO_CONTENT, None, {})


def redirect(location, cookies=None):
    return Response(
        "",
        HTTPStatus.SEE_OTHER,
        None,
        {"Location": location},
        _we_got_cookies(cookies or {}),
    )


def _plain_response(status):
    return Response(status.phrase, status, "text/plain", {})


_BAD_REQUEST = _plain_response(HTTPStatus.BAD_REQUEST)
_NOT_FOUND = _plain_response(HTTPStatus.NOT_FOUND)
_SERVER_ERROR = _plain_response(HTTPStatus.INTERNAL_SERVER_ERROR)


async def _write_response(writer, response, connection=None):
    body = (
        response.body.encode("utf-8")
        if isinstance(response.body, str)
        else response.body
    )
    header_buffer = [
        f"HTTP/1.1 {response.status.value} {response.status.phrase}",
        f"Content-Length: {len(response.body)}",
    ]
    if response.content_type:
        header_buffer += [f"Content-Type: {response.content_type}"]
    if connection:
        header_buffer += [f"Connection: {connection}"]
    for header, value in response.headers.items():
        header_buffer += [f"{header}: {value}"]
    for cookie in response.cookies:
        header_buffer += [f"Set-Cookie: {cookie}"]
    header = "\r\n".join(header_buffer).encode()
    header += b"\r\n\r\n"

    writer.write(header + body)
    await writer.drain()


# STATIC

_STATIC_DIR = Path.cwd() / "static"

for _ext, _type in {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
}.items():
    mimetypes.add_type(_type, _ext)


async def _static_response(request):
    try:
        candidate = (_STATIC_DIR / request.path.removeprefix("/static/")).resolve()

        if not (candidate.is_relative_to(_STATIC_DIR) and candidate.is_file()):
            return _NOT_FOUND

        candidate_stat = candidate.stat()
        etag = f'"{candidate_stat.st_mtime_ns:x}-{candidate_stat.st_size:x}"'
        if request.headers.get("if-none-match") == etag:
            return Response("", HTTPStatus.NOT_MODIFIED, None, {"ETag": etag})

        body = await asyncio.to_thread(candidate.read_bytes)  # no timeout here???

    except (OSError, ValueError):
        return _NOT_FOUND

    mime = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"

    return Response(body, HTTPStatus.OK, mime, {"ETag": etag})


# SSE


def patch(data):
    lines = ["event: datastar-patch-elements"]
    lines += [f"data: elements {line}" for line in data.splitlines()]

    return "\n".join(lines) + "\n\n"


_SSE_HEAD = (
    b"HTTP/1.1 200 OK\r\n"
    b"Content-Type: text/event-stream\r\n"
    b"Cache-Control: no-cache\r\n"
    b"Connection: close\r\n\r\n"
)


async def _stream_sse(writer, gen):
    try:
        writer.write(_SSE_HEAD)
        async with aclosing(gen) as stream:
            async for event in stream:
                writer.write(event.encode())
                await writer.drain()
    except (asyncio.CancelledError, ConnectionError):
        pass


# HANDLER

MAX_REQUESTS_PER_CONNECTION = 1000


async def _handle(reader, writer):
    try:
        for _ in range(MAX_REQUESTS_PER_CONNECTION):
            try:
                request = await _read_request(reader)
            except (ValueError, TimeoutError):
                await _write_response(writer, _BAD_REQUEST)
                return
            if request is None:
                return

            if request.method == "GET" and request.path.startswith("/static/"):
                response = await _static_response(request)
            else:
                handler, request.params = _find_handler(request.method, request.path)

                response = None
                for fn in _before_request:
                    response = fn(request)
                    if response is not None:
                        break

                if response is None:
                    if handler is None:
                        response = _NOT_FOUND
                    else:
                        result = handler(request)
                        if inspect.isasyncgen(result):  # sse patch
                            await _stream_sse(writer, result)
                            return
                        response = await result

            connection = _should_keep_alive(request)
            await _write_response(writer, response, connection=connection)

    except ConnectionError:  # client left
        return

    except Exception:  # no choice, can be anything
        logger.exception("Error handling request.")
        await _write_response(writer, _SERVER_ERROR)

    finally:
        writer.close()


# SERVER

MAX_LINE = 8_192  # bytes


async def _serve(host, port, sock):
    if sock:
        if os.name == "nt":
            raise OSError("Are you on Windows? Use host+port instead")
        old = os.umask(0o117)
        try:
            server = await asyncio.start_unix_server(_handle, path=sock, limit=MAX_LINE)
        finally:
            os.umask(old)
        logger.info(f"Listening on socket:{sock}")
    else:
        server = await asyncio.start_server(_handle, host, port, limit=MAX_LINE)
        logger.info(f"Listening on http://{host}:{port}")

    await server.serve_forever()


# MAIN


def _watch_for_changes():
    def iter_watched_files():
        yield from Path.cwd().glob("*.py")
        yield from (Path.cwd() / "static").rglob("*")

    mtimes = {}

    while True:
        time.sleep(1)
        for file_path in iter_watched_files():
            try:
                mtime = file_path.stat().st_mtime
            except OSError:
                return file_path.name
            key = str(file_path.resolve())
            if key in mtimes and mtime > mtimes[key]:
                return file_path.name
            else:
                mtimes[key] = mtime


_CHILD_ENV = "RED_DWARF_CHILD"


def _run_with_reload():
    command = [sys.executable, *sys.argv]
    env = {**os.environ, _CHILD_ENV: "1"}
    while True:
        child = subprocess.Popen(command, env=env)
        try:
            changed = _watch_for_changes()
            logger.info("Change detected in %s, restarting...", changed)
        finally:
            child.kill()
            child.wait(timeout=2)


def run(host="127.0.0.1", port=8080, sock=None, reload=False):
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    is_child = bool(os.environ.get(_CHILD_ENV))

    if not is_child:
        logger.info("Hello and welcome!")
        logger.info("Thank you for using Red Dwarf.")
        logger.info("Here are some recommendations to start:")
        logger.info("1. Read the Tao of Datastar")
        logger.info("2. Remember to escape user input")
        logger.info("3. ???")
        logger.info("4. Profit!")

    if reload and not is_child:
        with suppress(KeyboardInterrupt):
            _run_with_reload()
    else:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        asyncio.run(_serve(host, port, sock))

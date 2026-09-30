"""The wire (𝅘𝅥𝅯 dou dou doum 𝅘𝅥𝅮): turning bytes into a Request, and a Response back into bytes.

If you're looking for the public interface (rd.get, rd.html, rd.run...),
that's in red_dwarf.py.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from html import escape
from http import HTTPStatus
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, unquote, urlsplit

logger = logging.getLogger(__name__)


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
# PS: Adam said we could use @property for stuff like body, params...what do YOU think?

@dataclass(slots=True)
class Response:
    body: str | bytes
    status: str
    content_type: str
    headers: dict

# SECURITY

MAX_BODY_SIZE = 1_048_576  # bytes
MAX_HEADER_LINE = 8_192  # bytes


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
    try:
        async with asyncio.timeout(timeout):
            line = await reader.readline()

            if not line:
                return None

            parts = line.decode("utf-8", errors="replace").split()
            # maybe use surrogateescape instead?
            # we can't get back overwrittent values...
            # good
            if len(parts) < 2:
                return None

            method, raw_path = parts[0], parts[1]
            version = parts[2] if len(parts) > 2 else "HTTP/1.0"
            logger.info(f"Received {method} request on {escape(raw_path)}")  # telemetry ftw

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
                name = name.strip().lower()
                if name == "content-length" and name in headers:
                    return None  # two Content-Length headers smells like smuggling
                headers[name] = value.strip()
                # headers are overwritten otherwise, because we don't like shenanigans

            if "chunked" in headers.get("transfer-encoding", "").lower():
                return None  # yeah, we don't do that here...

            cookies = {}
            if cookie := headers.get("cookie"):
                try:
                    c = SimpleCookie(cookie)
                    for key, morsel in c.items():
                        cookies[key] = morsel.value
                except Exception as e:
                    logger.error(e)

            body = b""
            try:
                content_length = int(headers.get("content-length", 0))
                if content_length > MAX_BODY_SIZE:
                    return None  # too big: close the connection, don't desync it
                if content_length > 0:
                    body = await reader.readexactly(content_length)
            except ValueError:

                return None

            split = urlsplit(raw_path)
            path = unquote(split.path) or "/"
            query = parse_qs(split.query)
            # i don't see why you'd need more info from the split

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
    # add the headers and send the bytes
    if not isinstance(response.body, bytes):
        response.body = response.body.encode("utf-8")
    header_buffer = [
        f"HTTP/1.1 {response.status.value} {response.status.phrase}",
        f"Content-Length: {len(response.body)}",
    ]
    if response.content_type:
        header_buffer += [f"Content-Type: {response.content_type}"]
    if connection:
        header_buffer += [f"Connection: {connection}"]
    for header in response.headers:
        header_buffer += [f"{header}"]
    header = "\r\n".join(header_buffer)
    header += "\r\n\r\n"
    header = header.encode("utf-8")

    writer.write(header + response.body)
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

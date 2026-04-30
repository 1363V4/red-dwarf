import asyncio
import json
import mimetypes
import os
import signal
import sys
import threading
import time
import traceback
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


# --- small response helpers ---
def cookie(
    key, value, path="/", max_age=None, secure=True, httponly=True, samesite="Lax"
):
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


def html(body, status=HTTPStatus.OK, headers=None):
    return (body, status, "text/html", headers or [])


def empty():
    return "", HTTPStatus.NO_CONTENT, None, []


# request


def _read_signals(method, headers, params, body):
    # meh, not a fan of the control flow
    if "datastar-request" not in headers:
        return {}
    if method in ("GET", "DELETE"):
        data = params.get("datastar")
    elif headers.get("content-type") == "application/json":
        data = body.decode("utf-8", errors="replace")
    else:
        return {}
    return json.loads(data) if data else {}


class Request:
    """
    Tiny request container.

    This is intentionally not a full-featured request object. It only stores
    the small amount of data that this toy server can currently parse:
    - HTTP method
    - raw path
    - parsed path without query string
    - query dict where values are lists (same as urllib.parse.parse_qs)
    - headers as a lowercase-key dict
    - raw body bytes
    ...
    meh
    you are the only stateful focker aren't you
    we'll take care of you later
    ...
    slots? why not
    en fait property ça permet avec le decorator de mettre un docstring facile
    on valide ou pas ?
    """

    def __init__(self, method, raw_path, path, query, headers, body):
        self.method = method
        self.query = query
        self.headers = headers
        self.body = body
        self.signals = _read_signals(method, headers, query, body)
        # sus values
        self.text = self.body.decode("utf-8", errors="replace")
        self.raw_path = raw_path
        self.path = path
        # self.regex = {'id': str, ...}
        # pas de raison que le delimiter soit autre chose que /


# App starts here


def _watch_and_restart():
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


# ROUTING / APP STARTS HERE

_routes = {}


def _add(method, path):
    """Decorator used by get/post/put/delete."""

    def decorator(fn):
        _routes[(method, path)] = fn
        return fn

    return decorator


def get(path):
    return _add("GET", path)


def post(path):
    return _add("POST", path)


def put(path):
    return _add("PUT", path)


def delete(path):
    return _add("DELETE", path)


async def _read_request(reader):
    """
    Read and parse a single HTTP/1.1 request from the stream.

    Still intentionally small:
    - no chunked transfer decoding
    - no multipart parser
    - minimal header handling
    """
    line = await reader.readline()
    if not line:
        return None

    parts = line.decode("utf-8", errors="replace").split()
    if len(parts) < 2:
        return None

    method, raw_path = parts[0], parts[1]
    split = urlsplit(raw_path)
    path = split.path or "/"

    query = parse_qs(split.query)

    # Read headers until the blank separator line.
    headers = {}
    while True:
        header_line = await reader.readline()
        if header_line in (b"\r\n", b"\n", b""):
            break

        decoded = header_line.decode("utf-8", errors="replace").strip()
        if ":" not in decoded:
            # Skip malformed header lines instead of crashing.
            continue
        name, value = decoded.split(":", 1)
        headers[name.strip().lower()] = value.strip()

    # Read request body if Content-Length is present and valid.
    body = b""
    try:
        content_length = int(headers.get("content-length", 0))
        if content_length > 0:
            body = await reader.readexactly(content_length)
    except ValueError:
        pass

    return Request(method, raw_path, path, query, headers, body)


async def _send(writer, body_text, status, content_type, headers):
    """
    Write a minimal HTTP response to the stream.

    The body is always encoded as UTF-8 text.
    """
    body = body_text.encode("utf-8")
    header = (
        f"HTTP/1.1 {status.value} {status.phrase}\r\nContent-Length: {len(body)}\r\n"
    )
    if content_type:
        header += f"Content-Type: {content_type}\r\n"
    header += "\r\n"
    writer.write(header.encode("utf-8") + body)
    await writer.drain()


async def _serve(host, port, sock):
    async def handle(reader, writer):
        """
        Single-connection request handler.

        This implementation handles one request per connection and then closes
        the socket. It does not attempt keep-alive reuse.
        """
        try:
            request = await _read_request(reader)
            if request is None:
                return

            handler = _routes.get((request.method, request.path))

            if handler is None:  # unknown route, try static and if not return 500
                candidate = Path("static") / request.path.removeprefix("/static/")
                candidate = candidate.resolve()
                if (
                    request.method == "GET"
                    and candidate.is_relative_to(Path("static").resolve())
                    and candidate.is_file()
                ):
                    mime, _ = mimetypes.guess_type(candidate.name)
                    body = candidate.read_bytes()
                    writer.write(
                        f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\nContent-Type: {mime or 'application/octet-stream'}\r\n\r\n".encode()
                        + body
                    )
                    await writer.drain()
                else:
                    await _send(
                        writer,
                        "grug not know this path",
                        HTTPStatus.NOT_FOUND,
                        "text/plain",
                        [],
                    )
                return

            response = await handler(request)
            await _send(writer, *response)

        except Exception as e:
            print(f"grug had problem: {e}")
            traceback.print_exc()
            await _send(
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
    """Synchronous entry point for running the async server."""
    if reload:
        t = threading.Thread(target=_watch_and_restart, daemon=True)
        t.start()
    try:
        asyncio.run(_serve(host, port, sock))
    except KeyboardInterrupt:
        print("grug: out.")

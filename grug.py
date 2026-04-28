import asyncio
import inspect
import json
import mimetypes
import os
import signal
import sys
import threading
import time
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
    return "", HTTPStatus.NO_CONTENT, None


# request


def _read_signals(method, headers, params, body):
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
    slots?
    """

    def __init__(self, method, raw_path, path, query, headers, body):
        self.method = method
        self.raw_path = raw_path
        self.path = path
        self.query = query
        self.headers = headers
        self.body = body
        self.signals = _read_signals(method, headers, query, body)

    @property
    def text(self):
        """
        Decode body as UTF-8 text.

        `errors="replace"` avoids exceptions for malformed bytes and keeps
        the server behavior stable.
        """
        return self.body.decode("utf-8", errors="replace")


# App starts here


def _watch_and_restart():
    """
    Restart the process when any loaded .py file or static asset changes.
    grug asked claude if can do with asyncio, but claude said threading better.
    """
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
                os.execv(sys.executable, [sys.executable] + sys.argv)
        time.sleep(1)


class App:
    def __init__(self):
        # Route table key: (METHOD, PATH) -> handler function.
        self._routes = {}

    def get(self, path):
        return self._add("GET", path)

    def post(self, path):
        return self._add("POST", path)

    def put(self, path):
        return self._add("PUT", path)

    def delete(self, path):
        return self._add("DELETE", path)

    def _add(self, method, path):
        """Decorator used by get/post/put/delete."""

        def decorator(fn):
            self._routes[(method, path)] = fn
            return fn

        return decorator

    def run(self, host="127.0.0.1", port=8080, sock=None, reload=False):
        """Synchronous entry point for running the async server."""
        if reload:
            t = threading.Thread(target=_watch_and_restart, daemon=True)
            t.start()
        try:
            asyncio.run(self._serve(host, port, sock))
        except KeyboardInterrupt:
            print("grug: out.")

    async def _serve(self, host, port, sock):
        # Close over route table to avoid repeated attribute lookups.
        routes = self._routes

        async def handle(reader, writer):
            """
            Single-connection request handler.

            This implementation handles one request per connection and then closes
            the socket. It does not attempt keep-alive reuse.
            """
            try:
                request = await _read_request(reader)
                if request is None:
                    # Empty or malformed request line; close quietly.
                    return

                fn = routes.get((request.method, request.path))

                if fn is None:
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
                        )
                    return

                # Handlers can be sync or async.
                # If async, await; if sync, use value directly.
                result = fn(request)
                if inspect.isawaitable(result):
                    result = await result

                await _send(writer, *result)

            except Exception:
                # Tiny but important safety net:
                # convert unexpected exceptions into a controlled 500 response.
                await _send(
                    writer,
                    "grug make accident",
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "text/plain",
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

    # willkommen... hmmmmmmmmmmmmmmmm
    # false? yes
    # query = parse_qs(split.query, keep_blank_values=True)
    query = parse_qs(split.query)
    # query = {k: v[0] if len(v) == 1 else v for k, v in query.items()}

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
    content_length = 0
    length_value = headers.get("content-length")
    if length_value:
        try:
            content_length = int(length_value)
        except ValueError:
            content_length = 0

    body = b""
    if content_length > 0:
        body = await reader.readexactly(content_length)

    return Request(method, raw_path, path, query, headers, body)


async def _send(writer, body_text, status, content_type):
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

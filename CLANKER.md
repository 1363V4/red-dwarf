# Red Dwarf: Code Breakdown and Analysis

## Overview

Red Dwarf is a \~500-line, standard-library-only HTTP/1.1 server built on `asyncio` streams. It is designed for Datastar (hypermedia over SSE) and is meant to sit behind a reverse proxy, with Caddy mentioned in the keep-alive comment.

The core idea is that a server is `f(request) -> HTML`, so it provides routing, request parsing, a few response helpers, static files, and an SSE helper—and nothing else.

It requires Python 3.11+ (`asyncio.timeout`, plus `dataclass(slots=True)` and `aclosing` from Python 3.10).

### Usage

Assuming the file is saved as `rd.py`:

```
import rd@rd.get("/users/<id>")async def user(request):    return rd.html(f"<h1>User {escape(request.params['id'])}</h1>")@rd.get("/clock")async def clock(request):  # async generator = SSE stream    while True:        yield rd.patch(            f"<div id='clock'>{time.strftime('%X')}</div>"        )        await asyncio.sleep(1)rd.run(reload=True)
```

## Request Lifecycle

1. `_handle` is called once per TCP connection and loops while keep-alive is active.
2. `_read_request` parses the request line, headers, cookies, body, and Datastar signals, all under a timeout.
3. `GET /static/...` goes straight to `_static_response`.
4. Otherwise, the route is matched, then each `before_request` hook runs. The first hook to return a `Response` short-circuits processing.
5. If there is no route, the server returns a `404` and closes the connection.
6. The handler is called:
   - If it returns an async generator, it is streamed as SSE.
   - Otherwise, it is awaited for a `Response`.
7. `_write_response` serializes the response, and the loop continues or closes.

## Section-by-Section Breakdown

### 1. Routes

- `_routes` is a module-level list of `Route(method, regex, param_names, handler)`.
- `@get`, `@post`, `@put`, and `@delete` append to it.
- `_path_to_regex` turns `/users/<id>` into `^/users/([^/]+)$`.
- Each parameter matches exactly one path segment. The `"/path/<_>"` wildcard comment is a workaround, but it still only matches one segment.
- `_find_handler` is a linear, first-match scan.
- A wrong method on a known path produces a `404`, not a `405`.
- `before_request` hooks are plain synchronous functions.

### 2. Requests

`Request` is a slotted dataclass holding:

- The HTTP method.
- The raw and decoded path.
- The query string.
- Lowercase headers.
- The raw body.
- Datastar signals.
- Cookies.
- Route parameters.

#### Datastar Signals

`_read_signals` reads Datastar state only when the `datastar-request` header is present.

- For `GET` and `DELETE`, it parses the `datastar` query parameter as JSON.
- Otherwise, it parses a JSON body.
- Invalid data results in `{}`.

#### Request Parsing and Validation

`_read_request` is deliberately paranoid:

- The request line and each header line are capped at 8 KiB.
- The body is capped at 1 MiB.
- A duplicate `Content-Length` is rejected.
- Chunked transfer encoding is rejected.
- EOF mid-headers is rejected.
- Malformed header lines are skipped.
- Other duplicate headers are overwritten.
- Any failure returns `None`, which becomes a `400` response.

#### Keep-Alive

`_should_keep_alive` follows HTTP/1.1 defaults:

- HTTP/1.1: keep-alive.
- HTTP/1.0: close.
- The `Connection` header overrides both defaults.

### 3. Responses

`Response` holds the body, status, content type, and headers.

#### Response Helpers

| Helper       | Purpose                                      |
| ------------ | -------------------------------------------- |
| `html()`     | Returns a `200 OK` response.                 |
| `empty()`    | Returns a `204 No Content` response.         |
| `redirect()` | Returns a `307 Temporary Redirect` response. |

`html(cookies=...)` sets the following attributes on every cookie:

- `Secure`
- `HttpOnly`
- `SameSite=Lax`
- `Path=/`

These are sensible security defaults, assuming HTTPS is used.

#### Writing Responses

- `_write_response` computes `Content-Length`, encodes the body, and sends the headers and body in one write.
- `_bad_request`, `_not_found`, and `_server_error` generate plain-text errors that always send `Connection: close`.

### 4. Static Files

Static files are served from `./static`.

- The requested path is resolved using `resolve()` and must remain inside the static directory, as checked by `is_relative_to()`. This blocks `..` traversal and symlink escapes.
- The ETag is based on modification time and file size, represented in hexadecimal.
- `If-None-Match` returns `304 Not Modified`.
- MIME types for JavaScript, CSS, and SVG are registered explicitly, so they do not depend on the operating system's MIME registry.

The static-file `404` builds its own `Response` instead of using `_not_found`, because `_not_found` closes the connection. That is why the author's comment says it "bothers me."

### 5. Server-Sent Events (SSE)

#### Datastar Patches

`patch(html)` emits the `datastar-patch-elements` event:

```
event: datastar-patch-elements
data: elements <html content>
```

Each line is prefixed with `data: elements`. Prefixing every line also prevents SSE field injection through newlines in the HTML.

#### Streaming

`_stream_sse`:

1. Sends the response headers.
2. Iterates over the async generator.
3. Writes each event to the connection.

The generator is wrapped in `aclosing`, ensuring its `finally` blocks run when the client disconnects.

The response uses `Connection: close`, and the stream ends by closing the socket.

#### Limitations

Only `datastar-patch-elements` is supported. There is no:

- Signal patching.
- Selector or mode options.
- Event IDs.
- Retry configuration.

### 6. Server and Reload

`_serve` supports both TCP and Unix sockets.

#### Unix Sockets

- Removes a stale socket file.
- Sets the socket permissions to `660` using `chmod`.

#### Development Reloading

With `reload=True`:

1. A parent process starts.
2. The parent spawns the actual server as a child, marked by the `RED_DWARF_CHILD` environment variable.
3. The parent polls `*.py` modification times every second.
4. When a change is detected, the child process is restarted.

`SIGTERM` calls `server.close`.

## Strengths

- Readability: The code is compact, and the comments explain the design intent.
- Security: The defaults are mostly sensible, including loopback binding, traversal-safe static files, request-size limits, timeouts, and anti-smuggling checks.
- Natural streaming: Async generators make SSE straightforward to implement.
- Zero dependencies: Everything is implemented using Python's standard library.
- Clear scope: The server focuses on routing, HTML responses, static files, and Datastar integration rather than becoming a full application framework.

## Deliberately Omitted Features

Many missing features are intentionally delegated to Caddy or another reverse proxy.

| Feature             | Design implication                                                                                   |
| ------------------- | ---------------------------------------------------------------------------------------------------- |
| TLS                 | HTTPS is expected to be handled by the reverse proxy.                                                |
| Compression         | Response compression is left to the proxy.                                                           |
| HTTP/2              | The server only implements HTTP/1.1.                                                                 |
| Slow-client defense | More advanced client buffering and connection management are left to the surrounding infrastructure. |

Overall, Red Dwarf is a deliberately small HTTP server built around a simple model: parse a request, route it to a handler, and return HTML or stream updates over SSE. Its simplicity is a strength, provided the deployment environment supplies the infrastructure and protections that the server intentionally omits.

from http import HTTPStatus
import asyncio
import inspect
import os
import signal
from urllib.parse import urlsplit, parse_qs


# --- small response helpers ---
#
# Every handler returns a 3-tuple:
#   (body_text, status, content_type)
#
# Keeping this shape tiny and explicit makes the server easy to reason about.
def html(body, status=HTTPStatus.OK):
	"""Return an HTML response tuple."""
	return body, status, "text/html"


def text(body, status=HTTPStatus.OK):
	"""Return a plain-text response tuple."""
	return body, status, "text/plain"


def empty():
	"""Return a 204 No Content response tuple."""
	return "", HTTPStatus.NO_CONTENT, None


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
	"""

	def __init__(self, method, raw_path, path, query, headers, body):
		self.method = method
		self.raw_path = raw_path
		self.path = path
		self.query = query
		self.headers = headers
		self.body = body

	@property
	def text(self):
		"""
		Decode body as UTF-8 text.

		`errors="replace"` avoids exceptions for malformed bytes and keeps
		the server behavior stable.
		"""
		return self.body.decode("utf-8", errors="replace")


class App:
	"""
	Minimal async HTTP app.

	Design goals:
	- tiny API surface
	- easy to read and hack on
	- enough structure to grow incrementally
	"""

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

	def run(self, host="127.0.0.1", port=8080, sock=None):
		"""Synchronous entry point for running the async server."""
		asyncio.run(self._serve(host, port, sock))

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
					await _send(writer, "grug not know this path", HTTPStatus.NOT_FOUND, "text/plain")
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
				await _send(writer, "grug make accident", HTTPStatus.INTERNAL_SERVER_ERROR, "text/plain")
			finally:
				writer.close()
				await writer.wait_closed()

		# Bind either to a Unix domain socket or a TCP host/port.
		if sock:
			if os.name == "nt":
				raise OSError("grug on windows — unix socket not available, use host+port instead")
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
	query = parse_qs(split.query, keep_blank_values=True)

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
	header = f"HTTP/1.1 {status.value} {status.phrase}\r\nContent-Length: {len(body)}\r\n"
	if content_type:
		header += f"Content-Type: {content_type}\r\n"
	header += "\r\n"
	writer.write(header.encode("utf-8") + body)
	await writer.drain()

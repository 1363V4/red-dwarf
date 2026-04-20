from http import HTTPStatus
import asyncio
import inspect
import signal
import os


# --- grug response helpers ---


def html(body, status=HTTPStatus.OK):
	return body, status, "text/html"


def empty():
	return "", HTTPStatus.NO_CONTENT, None


# --- grug app ---


class App:
	def __init__(self):
		self._routes = {}

	def get(self, path):    return self._add("GET", path)
	def post(self, path):   return self._add("POST", path)
	def put(self, path):    return self._add("PUT", path)
	def delete(self, path): return self._add("DELETE", path)

	def _add(self, method, path):
		def decorator(fn):
			self._routes[(method, path)] = fn
			return fn
		return decorator

	def run(self, host="127.0.0.1", port=8080, sock=None):
		asyncio.run(self._serve(host, port, sock))

	async def _serve(self, host, port, sock):
		routes = self._routes  # close over — handler sees routes, nothing else does

		async def handle(reader, writer):
			try:
				line = await reader.readline()
				parts = line.decode().split()
				if len(parts) < 2:
					return
				method, path = parts[0], parts[1]

				# drain headers — grug not need them yet
				while True:
					if await reader.readline() in (b"\r\n", b"\n", b""):
						break

				fn = routes.get((method, path))
				if fn is None:
					await _send(writer, "grug not know this path", HTTPStatus.NOT_FOUND, "text/plain")
					return

				result = fn()
				if inspect.isawaitable(result):  # async fn? grug await. sync fn? grug not bother
					result = await result
				await _send(writer, *result)

			finally:
				writer.close()
				await writer.wait_closed()

		if sock:
			if os.name == "nt":
				raise OSError("grug on windows — unix socket not available, use host+port instead")
			if os.path.exists(sock):
				os.unlink(sock)
			server = await asyncio.start_unix_server(handle, path=sock)
			os.chmod(sock, 0o660)  # grug protect socket — note: silently ignored on windows
			print(f"grug listen on unix:{sock}")
		else:
			server = await asyncio.start_server(handle, host, port)
			print(f"grug listen on http://{host}:{port}")

		# SIGTERM: nginx/docker use this — without it, unix socket left behind like mammoth bone
		if hasattr(signal, "SIGTERM"):
			signal.signal(signal.SIGTERM, lambda *_: server.close())

		async with server:
			await server.serve_forever()


async def _send(writer, body_text, status, content_type):
	body = body_text.encode()
	header = f"HTTP/1.1 {status.value} {status.phrase}\r\nContent-Length: {len(body)}\r\n"
	if content_type:
		header += f"Content-Type: {content_type}\r\n"
	header += "\r\n"
	writer.write(header.encode() + body)
	await writer.drain()


# --- grug routes ---


app = App()


@app.get("/")
def index():
	return html("<h1>grug server</h1>")


@app.get("/club")
async def club():                          # async, grug can now go hunt while waiting
	await asyncio.sleep(0)                 # pretend grug fetch mammoth from database
	return html("<h1>grug club very heavy</h1>")


@app.post("/club")
async def smash_club():
	return empty()


app.run()
# app.run(sock="/tmp/grug.sock")

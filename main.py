from http.server import HTTPServer, BaseHTTPRequestHandler
from http import HTTPStatus
import socket
import signal
import os

# grug route brain
routes = {}


def route(method, path):
	def decorator(fn):
		routes[(method.upper(), path)] = fn
		return fn

	return decorator


# --- grug response helpers ---


def html(body, status=HTTPStatus.OK):
	return body, status, "text/html"


def empty():
	return "", HTTPStatus.NO_CONTENT, None


# --- grug routes ---


@route("GET", "/")
def index():
	return html("<h1>grug server</h1>")


@route("GET", "/club")
def club():
	return html("<h1>grug club very heavy</h1>")


@route("POST", "/club")
def smash_club():
	return empty()


# --- boring server stuff, grug rarely touch ---


class GrugHandler(BaseHTTPRequestHandler):
	def handle_any(self):
		handler_fn = routes.get((self.command, self.path))
		if handler_fn is None:
			send_response(
				self, HTTPStatus.NOT_FOUND, "grug not know this path", "text/plain"
			)
			return
		body, status, content_type = handler_fn()
		send_response(self, status, body, content_type)

	def do_GET(self):
		self.handle_any()

	def do_POST(self):
		self.handle_any()

	def log_message(self, format, *args):
		pass


def send_response(handler, status, body_text, content_type):
	body = body_text.encode()
	handler.send_response(status)
	if content_type:
		handler.send_header("Content-Type", content_type)
	handler.send_header("Content-Length", len(body))
	handler.end_headers()
	handler.wfile.write(body)


class UnixServer(HTTPServer):
	address_family = socket.AF_UNIX

	def server_close(self):
		super().server_close()
		os.unlink(self.server_address)  # clean up socket file


def run_server(host="127.0.0.1", port=8080, path=None):
	# grug smart - pick server type from arguments
	if path:
		if os.path.exists(path):
			os.unlink(path)
		server = UnixServer(path, GrugHandler)
		os.chmod(path, 0o660)  
		# grug protect socket from strangers
		print(f"grug listen on unix:{path}")
	else:
		server = HTTPServer((host, port), GrugHandler)
		print(f"grug listen on http://{host}:{port}")

	# signal reason: Ctrl+C (SIGINT) fine without this
	# but nginx/docker send SIGTERM to stop server - that one skips cleanup!
	# without this, unix socket file left behind like mammoth bone
	signal.signal(signal.SIGTERM, lambda *_: server.shutdown())

	server.serve_forever()  # already handles Ctrl+C cleanly


run_server()
# run_server(path="/tmp/grug.sock")")")

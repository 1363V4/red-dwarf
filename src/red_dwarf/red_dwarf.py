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
#
# This file is the main interface,: `import red_dwarf as rd`, then rd.get,
# wire.py is bytes in, bytes out (Request and Response), 
# and server.py is routes and connections.

import asyncio
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from .server import _STATIC_DIR, _serve, before_request, delete, get, post, put
from .wire import empty, html, patch, redirect

__version__ = "0.1.0"

__all__ = (
	"__version__",
	"before_request",
	"delete",
	"empty",
	"get",
	"html",
	"patch",
	"post",
	"put",
	"redirect",
	"run",
)

logger = logging.getLogger(__name__)

_CHILD_ENV = "RED_DWARF_CHILD"  # set for the reloaded child: it just serves

# APP


def _watch_for_changes():
	def iter_watched_files():
		yield from Path.cwd().rglob("*.py")
		if _STATIC_DIR.is_dir():
			yield from _STATIC_DIR.rglob("*")

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

def _run_with_reload(host, port, sock):
	command = [sys.executable, *sys.argv]
	env = {**os.environ, _CHILD_ENV: "1"}
	while True:
		child = subprocess.Popen(command, env=env)
		try:
			changed = _watch_for_changes()
			logger.info("Change detected in %s, restarting...", changed)
		finally:
			child.terminate()
			child.wait()


def run(host="127.0.0.1", port=8080, sock=None, reload=False):
	logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

	if os.environ.get(_CHILD_ENV):  # we are the reloaded child: just serve
		asyncio.run(_serve(host, port, sock))
		return

	logger.info("Hello and welcome!")
	logger.info("Thank you for using Red Dwarf.")
	logger.info("Here are some recommendations to start:")
	logger.info("1. Read the Tao of Datastar")
	logger.info("2. Remember to escape user input")
	logger.info("3. ???")
	logger.info("4. Profit!")
	try:
		if reload:
			_run_with_reload(host, port, sock)
		else:
			asyncio.run(_serve(host, port, sock))
	except KeyboardInterrupt:
		logger.info("Server shutdown.")
		
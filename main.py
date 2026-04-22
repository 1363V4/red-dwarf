import asyncio

# Keep `main.py` as demo website only.
# The reusable server core now lives in `grug.py`.
from grug import App, empty, html


# --- demo website routes ---
#
# This file is intentionally focused on "site behavior":
# route handlers, fake business logic, startup defaults.
# It should stay small and readable for quick experiments.
app = App()


@app.get("/")
def index(_request):
	# `_request` is accepted for consistency with all handlers.
	# This route ignores request details and returns static HTML.
	return html('''
<html lang="en">
<head>
    <meta charset="UTF-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
	<link rel="icon" href="/static/img/red_dwarf.png"/>
    <link rel="stylesheet" href="/static/css/index.css"/>
	<script type="module" src="/static/js/datastar.js"></script>
</head>
<body class="gc">
...
</body>
</html>
''')


@app.get("/club")
async def club(_request):
	# Async handler demo:
	# pretend we are waiting for database / API work.
	await asyncio.sleep(0)
	return html("<h1>grug club very heavy</h1>")


@app.post("/club")
async def smash_club(request):
	# Body access demo:
	# if user sends text body, we can inspect it via `request.text`.
	#
	# We keep behavior tiny for now and always return 204.
	_ = request.text
	return empty()


if __name__ == "__main__":
	# Import-safe startup:
	# the server runs only when this file is executed directly.
	# This makes tests/imports simpler and avoids accidental startup.
	app.run()
	# app.run(sock="/tmp/grug.sock")

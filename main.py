from html import escape
from pathlib import Path
from pprint import pprint

import other_site
import reddwarf as rd

HTML_PATH = Path().cwd() / "static" / "html"


with open(HTML_PATH / "index.html", "r") as f:
    PAGE_HOME = f.read()


@rd.before_request
def cookie_check(request):
    pass
    # pprint(request)


@rd.get("/")
async def index(request):
    with open(HTML_PATH / "index.html", "r") as f:
        PAGE_HOME = f.read()
    return rd.html(PAGE_HOME, headers=[rd.cookie("nusky", "vaati")])


@rd.get("/docs")
async def docs(request):
    with open(HTML_PATH / "docs.html", "r") as f:
        PAGE_DOCS = f.read()
    return rd.html(PAGE_DOCS)


@rd.post("/club")
async def smash_club(request):
    name = request.signals.get("name")
    if name:
        return rd.html(f"<p id=username>GRUG {escape(name)}</p>")
    else:
        return rd.empty()


@rd.get("/sse")
async def sse(request):
    return rd.html("""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
	<link rel="icon" href="/static/img/red_dwarf.png"/>
    <link rel="stylesheet" href="/static/css/index.css"/>
	<script type="module" src="/static/js/datastar.js"></script>
</head>
<body class="gf gc">
    <main id="main" data-init="@get('/sse_stream')">waiting for a stream</main>
</body>
</html>
""")


@rd.get("/sse_stream")
async def sse_stream(request):
    response = rd.patch("""
<main id="main">got it got it 2</main>
""")
    pprint(response)
    yield response


# @rd.get("/sse_stream")
# async def sse_stream(request):
#     response = rd.patch("""
# <main id="main">got it</main>
# """)
#     try:
#         while True:
#             yield response
#             await asyncio.sleep(1)
#     finally:
#             print("cleanup")

if __name__ == "__main__":
    rd.run(reload=True)
    # app.run(sock="/tmp/grug.sock")

# viande out

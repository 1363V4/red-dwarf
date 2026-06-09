import reddwarf as rd
from pprint import pprint
from html import escape


import other_site

with open("index.html", 'r') as f:
    PAGE_HOME = f.read()


@rd.get("/")
async def index(request):
    return rd.html(PAGE_HOME, headers=[rd.cookie("nusky", "vaati")])


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

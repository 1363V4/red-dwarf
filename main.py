# from html import escape

import other_site
import json
from importlib import import_module
from pathlib import Path
from pprint import pprint
from time import asctime

# from uuid import uuid4
import reddwarf as rd

HTML_PATH = Path().cwd() / "static" / "html"

import_module("other_site")

with open(HTML_PATH / "index.html", "r", encoding="utf8") as f:
    PAGE_HOME = f.read()

with open(HTML_PATH / "faq.html", "r", encoding="utf8") as f:
    PAGE_FAQ = f.read()

with open("database.json") as db:
    database = json.load(db)

# @rd.before_request
# def cookie_check(request):
#     pprint(request)
#     pass

# @rd.after_response
# def log(request, response):
#     print(f"Another successful response on {request.path}!")
#     response.body = response.body.replace("RED", "BLUE")
#     print(response)
#     return response

@rd.get("/")
async def index(request):
    print("BdE")
    # with open(HTML_PATH / "index.html", "r") as f:
    #     PAGE_HOME = f.read()
    return rd.html(PAGE_HOME, cookies={"laid": "up"})


@rd.get("/docs")
async def docs(request):
    with open(HTML_PATH / "docs.html", "r") as f:
        PAGE_DOCS = f.read()
    return rd.html(PAGE_DOCS, headers=["Wait: What"], cookies={"cbs": "bd", 'down': 0})


@rd.get("/red")
async def red(request):
    with open(HTML_PATH / "red.html", "r") as f:
        PAGE_RED = f.read()
    return rd.html(PAGE_RED)

@rd.get("/faq")
async def faq(request):
    return rd.html(PAGE_FAQ)


@rd.get("/redi")
async def redi(request):
    return rd.redirect("/")


@rd.post("/time")
async def time(request):
    time = asctime()
    # hmmm ptet script est bien
    # ajouter à un counter persisté
    database["asks"] += 1
    with open("database.json", "w") as db:
        json.dump(database, db)
    yield rd.patch(f'<div id=time>{time}</div>')
    yield rd.patch(f'<div id=brag>I\'ve been asked {database["asks"]} times</div>')


@rd.get("/docs/<folder_id>/<document_id>")
async def serve_document(request):
    print(request.method)
    # 'GET'
    print(request.raw_path)
    # '/docs/folder18/document4?page=42'
    print(request.path)
    # '/docs/folder18/document4'
    print(request.params)
    # {'folder_id': 'folder18', 'document_id': 'document4'}
    print(request.query)
    # {'page': ['2']}
    print(request.headers)
    # {'host': '...', ...}
    print(request.body)
    # b''
    print(request.signals)
    # {'theme': 'light'}
    return rd.html("ok")


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
    print(database)
    rd.run(reload=True)
    # app.run(sock="/tmp/grug.sock")

# viande out

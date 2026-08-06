# from html import escape

# import other_site ... i'll do that for examples page
import json
from pathlib import Path
from time import asctime
import logging

import red_dwarf as rd
from pages import (
    PAGE_INDEX, 
    ESSAY_V0, 
    PAGE_ESSAYS,
    PAGE_EXAMPLES,
    PAGE_FAQ,
    PAGE_RED,
    PAGE_GETTING_STARTED,
    PAGE_DOCS
    )


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger("MAIN")

_SITE_DIR = Path(__file__).resolve().parent
_DB_PATH = _SITE_DIR / "database.json"

with open(_DB_PATH) as db:
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
    logger.info("Hello there")
    return rd.html(PAGE_INDEX, cookies={"laid": "up"})


@rd.get("/docs")
async def docs(request):
    return rd.html(PAGE_DOCS, headers=["Wait: What"])


@rd.get("/red")
async def red(request):
    return rd.html(PAGE_RED)

@rd.get("/faq")
async def faq(request):
    return rd.html(PAGE_FAQ)

@rd.get("/getting_started")
async def start(request):
    return rd.html(PAGE_GETTING_STARTED)

@rd.get("/examples")
async def examples(request):
    return rd.html(PAGE_EXAMPLES)

@rd.get("/essays")
async def essays(request):
    return rd.html(PAGE_ESSAYS)


@rd.get("/redi")
async def redi(request):
    return rd.redirect("/")


@rd.post("/time")
async def time(request):
    time = asctime()
    # hmmm ptet script est bien
    # ajouter à un counter persisté
    database["asks"] += 1
    with open(_DB_PATH, "w") as db:
        json.dump(database, db)
    yield rd.patch(f'<div id=time>{time}</div>')
    yield rd.patch(f'<div id=brag>I\'ve been asked {database["asks"]} times</div>')


# @rd.get("/docs/<folder_id>/<document_id>")
# async def serve_document(request):
#     print(request.method)
#     # 'GET'
#     print(request.raw_path)
#     # '/docs/folder18/document4?page=42'
#     print(request.path)
#     # '/docs/folder18/document4'
#     print(request.params)
#     # {'folder_id': 'folder18', 'document_id': 'document4'}
#     print(request.query)
#     # {'page': ['2']}
#     print(request.headers)
#     # {'host': '...', ...}
#     print(request.body)
#     # b''
#     print(request.signals)
#     # {'theme': 'light'}
#     return rd.html("ok")

@rd.get("/essays/<essay>")
async def essay_page(request):
    # request should be req
    d_essay = {
        'v0': ESSAY_V0,
    }
    essay = request.params.get('essay')
    page = d_essay.get(essay)
    if page:
        return rd.html(page)
    else:
        return rd.redirect("/")

# @rd.get("/sse_stream")
# async def sse_stream(request):
#     try:
#         while True:
#             yield rd.patch("""
#         <main id="main">got it</main>
#         """)
#             await asyncio.sleep(1)
#     finally:
#         print("cleanup")

if __name__ == "__main__":
    rd.run(reload=True, static_dir=_SITE_DIR / "static")
    # app.run(sock="/tmp/grug.sock")
    # rd.run(sock="/run/legovh/rd.sock", reload=True)

# viande out

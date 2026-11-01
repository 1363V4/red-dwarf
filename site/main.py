# from html import escape

import json
import logging
from pathlib import Path
from time import asctime

import rd
from pages import (
    ESSAY_BOTTLE,
    ESSAY_DATASTAR,
    ESSAY_PYTHON,
    ESSAY_REAL,
    ESSAY_UV,
    ESSAY_V0,
    PAGE_DOCS,
    PAGE_ESSAYS,
    PAGE_EXAMPLES,
    PAGE_FAQ,
    PAGE_GETTING_STARTED,
    PAGE_INDEX,
    PAGE_RED,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger("MAIN")

_SITE_DIR = Path(__file__).resolve().parent
_DB_PATH = _SITE_DIR / "database.json"

with open(_DB_PATH) as db:
    database = json.load(db)


@rd.get("/")
async def index(request):
    logger.info("Hello there")
    return rd.html(PAGE_INDEX, cookies={"laid": "up"})


@rd.get("/docs")
async def docs(request):
    return rd.html(PAGE_DOCS, headers={"Wait": "What"})


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
    database["asks"] += 1
    with open(_DB_PATH, "w") as db:
        json.dump(database, db)
    yield rd.patch(
        f"<div id=time>Hi! I am a 3$ server in Germany and now is {time}</div>"
    )
    yield rd.patch(f"<div id=brag>I've been asked {database['asks']} times</div>")


@rd.get("/essays/<essay>")
async def essay_page(request):
    d_essay = {
        "v0.html": ESSAY_V0,
        "datastar.html": ESSAY_DATASTAR,
        "python.html": ESSAY_PYTHON,
        "real.html": ESSAY_REAL,
        "bottle.html": ESSAY_BOTTLE,
        "uv.html": ESSAY_UV,
    }
    essay = request.params.get("essay")
    page = d_essay.get(essay)
    if page:
        return rd.html(page)
    else:
        return rd.redirect("/")

if __name__ == "__main__":
    rd.run(reload=True)
    # rd.run(sock="/run/legovh/rd.sock")
    # i toggle between both for dev and prod

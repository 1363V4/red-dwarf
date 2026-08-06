# Red Dwarf

![Red Dwarf](site/static/img/logo_124.png)

**Website:** [red.leg.ovh](https://red.leg.ovh) · **Docs:** [/docs](https://red.leg.ovh/docs) · **FAQ:** [/faq](https://red.leg.ovh/faq) · **GitHub:** [1363V4/red-dwarf](https://github.com/1363V4/red-dwarf)

Red Dwarf is a zero-dependency async HTTP/1.1 server for Python, built around [Datastar](https://data-star.dev/). 

## Why Red Dwarf?

Datastar keeps application state on the backend. But the backend is more than a web server: it is also database, cronjobs, pub/sub, scripts... 

Red Dwarf does the smallest useful slice: parse HTTP, match routes, return HTML or stream patches. You write the rest of your Python however you like.

Red Dwarf is a good first step with Datastar. For multiple workers, middleware stacks, or heavy production tooling, look at [Stario](http://stario.dev/), [Sanic](https://sanic.dev/), or [Quart](https://quart.palletsprojects.com/).

## Requirements

- Python **3.11+** (see `pyproject.toml`)

## Install

It's not on Pypi yet (please give me a hand lol)
but you can get the code in src.

## Quickstart

Create `app.py`:

```python
import red_dwarf as rd

@rd.get("/")
async def index(request):
    return rd.html("<h1>Hello, world!</h1>")

if __name__ == "__main__":
    rd.run(reload=True)
```

Run it and open [http://127.0.0.1:8080/](http://127.0.0.1:8080/).

Handlers are **async** functions. Register them with `@rd.get`, `@rd.post`, `@rd.put`, or `@rd.delete`. Return `rd.html(...)` for pages, `rd.redirect(...)`, or `rd.empty()`. For live UI updates, make the handler an **async generator** and `yield rd.patch(...)` (Datastar SSE patches)—see [the site demo](https://red.leg.ovh/) and [reference](https://red.leg.ovh/docs).

Path parameters use angle brackets: `@rd.get("/essays/<essay>")` → `request.params["essay"]`.

## Reverse proxy

In production, terminating TLS and serving/cacheing static assets with [Caddy](https://caddyserver.com/) (or similar) is recommended. For **SSE** streams behind nginx, disable buffering (e.g. `X-Accel-Buffering: no` on the response).

## FAQ

Common questions (sync vs async, JSON, tests, compression, cookies, and more) live on the site: **[red.leg.ovh/faq](https://red.leg.ovh/faq)**.

## License

MIT — see [LICENSE](LICENSE).

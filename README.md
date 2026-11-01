# Red Dwarf

![Red Dwarf](site/static/img/logo_124.png)

**Website:** [red.leg.ovh](https://red.leg.ovh)

Red Dwarf is a zero-dependency async HTTP/1.1 server for Python, built around [Datastar](https://data-star.dev/).

## Why Red Dwarf?

Datastar supercharges the backend. **But the backend is more than a web server!**

So it is Red Dwarf's philosophy that the server should be as simple as possible,
because there are other fish to fry.

Red Dwarf does the smallest useful slice: parse HTTP, match routes, return HTML or stream patches. You write the rest of your backend (database, cronjobs, pub/sub, scripts...) however you like.

Red Dwarf is a good first step with Datastar. For multiple workers, middleware stacks, or production tooling, look at [Stario](http://stario.dev/), [Sanic](https://sanic.dev/), or [Quart](https://quart.palletsprojects.com/).

## Requirements

- Python **3.11+**

## Links

- [Getting Started](https://red.leg.ovh/getting_started)
- [Docs](https://red.leg.ovh/docs)
- [Essays](https://red.leg.ovh/essays)
- [FAQ](https://red.leg.ovh/faq)

## Quickstart

```python
import rd

@rd.get("/")
async def index(request):
    return rd.html("<h1>Hello, world!</h1>")

if __name__ == "__main__":
    rd.run(reload=True)
```

## License

MIT — see [LICENSE](LICENSE).

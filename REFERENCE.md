# Reference

redwarf is mostly made out of helper functions, which is why we recommend to import it with a namespace. For example:

```python
import redwarf as rd

...

rd.run()
```

## Main functions

### run()

> run(host="127.0.0.1", port=8080, sock=None, reload=False)

host: str: address, default is localhost
port: int: ...
socket : str : unix socket
reload : bool : just the python files and the static folder

## Helper functions

### html()
### empty()
### patch()
### cookies()

## Routing

### add/...
### before/after

before is if route found (wont fire for assets)
you can send response and it will cancel
after has response

## Request

### Attributes

self.method
self.raw_path
self.path
self.query
self.headers
self.body
self.signals
self.params

## Response

u shouldn't bother !!

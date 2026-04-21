# Red Dwarf User Manual

## Overview

### What is Red Dwarf?

Red Dwarf is a very minimal and very opinionated Python ASGI server.

Red Dwarf:

- only use the Python default library
- is fast
- has sensible helper functions
- is decently secure
- gets you running in seconds

### Why Red Dwarf?

First, Red Dwarf highly recommends [Datastar](https://data-star.dev/).

Datastar's philosophy (and Red Dwarf's) is
"keeping state in the backend".

But the "backend" is not equal to the "server", it's more than that.
It's your database, your cronjobs, your pubsub system, your other Python scripts...

Red Dwarf gets out of your way by doing what a server should do
(receiving and responding to Web requests)
and nothing more,
so you can write your Python however you see fit.

### How to use Red Dwarf?

Simply run `uv add red-dwarf` to your project to get going.
Then, head over to [Quickstart](#quickstart)

### When not to use Red Dwarf?

Red Dwarf is intended as a first "entry point" into the world of Datastar.

Don't use Red Dwarf if:

- you need multiple workers
- you need middlewares
- you need telemetry
- you need advanced server functions
- you're doing anything serious

We instead recommend the following tools:

- [Stario](http://stario.dev/), a complete Python + Datastar framework
- [Sanic](https://sanic.dev/)
- [Quart](https://quart.palletsprojects.com/)

## Quickstart

### Hello World

After installing `uv add red-dwarf`,
create a new file named `app.py` and write:

```python
from red_dwarf import App, Input, Output

app = App()

@app.get("/")
def index(i,o):
	return o.html("<h1>hello world!</h1>")

if __name__ == "__main__":
	app.run()
```

Open a web browser and go to `http://localhost:8080/`: you should see the hello world message.

What we did here:

- Created our server with `app = App()`
- Registered a handler `index` for GET request on the home page `@app.get("/")`
- Told the handler to output HTML
- Started the server with `app.run()`

### Your first app

Let's modify `app.py`:

```python
from red_dwarf import App, Input, Output

app = App()

@app.get("/")
def index(i,o):
	return o.html(
'''
<html lang="en">
<head>
    <meta charset="UTF-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <link rel="stylesheet" href="/static/css/index.css"/>
    <script type="module" src="/static/js/datastar.js">
</head>
<body class="gc">
...
</body>
</html>
'''
    )

if __name__ == "__main__":
	app.run()
```

We now have a proper HTML "file" (well, a string)
which now includes Datastar and 
gold.css.

You'll notice immediately that the page is reactive.
Go to localhost and fill the input: the text is updated on the frontend by Datastar.

Next, we'll add a route to react from the backend.
Start by modifying the index HTML to:

...

then add route "dwarf_name" like this:

...

Tada!

### Your first stream

Finally, let's see how alive and patch work by opening a SSE stream.

We start from our previous code:

...

And we modify the body to open a SSE stream:

...

Now we just need to add the SSE route:

...

Go to localhost and watch the dwarf count time!

## Reference

### App

#### Attributes
#### app.run()

### Input

#### Attributes
#### i.cookies()
#### i.signals()

### Output

#### Attributes
#### o.html()
#### o.empty()
#### o.alive()
#### o.patch()

## FAQ

**Question?**

Answer.

**Can I use sync functions?**

No. Everything in RD is async by default.

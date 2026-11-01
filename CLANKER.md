# AGENTS.md — Building Applications with Red Dwarf + Datastar

This file is the working guide for agents creating, extending, or reviewing an application built with **Red Dwarf**, **Datastar**, and optionally **Rocket**.

The intended architecture is deliberately small:

- **Red Dwarf** owns HTTP/1.1, routing, request parsing, HTML responses, static files, and async-generator SSE streams.
- **Datastar** owns declarative browser reactivity, backend requests, DOM morphing, and the browser-side connection to streams.
- **Rocket** is an optional layer for reusable, encapsulated web components. Use it when a UI element has a meaningful component API or needs JavaScript behavior that does not belong in a Datastar expression.

The backend is the source of truth. Prefer server-rendered HTML patches and short-lived commands over building a client-side application state machine.

---

## 1. Non-negotiable project conventions

1. **Use Python 3.11 or newer.** Red Dwarf uses `asyncio.timeout`; the documented implementation is standard-library-only.
2. **Keep Red Dwarf small.** Do not add Flask, FastAPI, Starlette, Django, an ASGI server, or a client-side framework to solve something Red Dwarf already handles.
3. **Use server-rendered HTML.** Route handlers return `rd.html(...)`, `rd.empty()`, `rd.redirect(...)`, or an async generator yielding `rd.patch(...)`.
4. **Let Datastar drive the DOM.** Use stable element IDs and the default morph strategy before reaching for custom JavaScript or alternative patching strategies.
5. **Keep durable application state on the backend.** Signals are for transient user interaction and for submitting user input, not as a second database in the browser.
6. **Prefer CQRS for live screens.** Open a long-lived read stream once; issue independent short-lived `POST`/`PUT`/`DELETE` commands that update backend state and publish an update to the stream. Commands normally return `rd.empty()`.
7. **Use Rocket for component boundaries, not as a replacement for Datastar.** Public component inputs are props; private reactive state is local Rocket state; component-originated notifications are events.
8. **Do not invent Red Dwarf APIs.** The Red Dwarf interface described here supports `rd.patch(html)` for `datastar-patch-elements`. It does not provide a first-class helper for `datastar-patch-signals`, custom SSE selectors/modes, event IDs, or retry settings.
9. **Keep user input out of executable Datastar expressions.** Expressions should be authored by the application and remain static. Pass user values as text, attributes, or signals and validate them on the server.
10. **Assume the application runs behind a reverse proxy.** Red Dwarf is not the TLS, compression, HTTP/2, or full production edge layer.

When the repository contains a local `rd.py` or another Red Dwarf implementation, inspect that source before relying on any detail not listed here. The supplied Red Dwarf notes describe a small implementation; they are not a promise that every feature in the Datastar reference is supported by Red Dwarf.

## 2. Quickstart

### Runtime and files

A minimal project can look like this:

```text
project/
├── app.py
├── rd.py                 # If the project vendors Red Dwarf as a module
└── static/
    ├── datastar.js       # Use this for Datastar-only pages
    ├── datastar-rocket.js # Use this instead when the page uses Rocket
    └── components/
        └── status-card.js
```

Red Dwarf serves files from `./static` at `/static/...`. The Datastar documentation recommends hosting the browser bundle yourself. Pin the bundle version used by the project and update it deliberately.

Choose **one** browser bundle per page:

```html
<!-- Datastar without Rocket -->
<script type="module" src="/static/datastar.js"></script>
```

```html
<!-- Datastar + Rocket; this bundle includes Datastar -->
<script type="module" src="/static/datastar-rocket.js"></script>
```

Do not load both bundles on the same page. The supplied Datastar docs show version `v1.0.4` and the corresponding `datastar.js` / `datastar-rocket.js` bundles. Prefer a locally hosted copy over a runtime CDN dependency.

### Smallest useful Red Dwarf app

```python
import rd


@rd.get("/")
async def home(request):
    return rd.html("""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Red Dwarf app</title>
    <script type="module" src="/static/datastar.js"></script>
</head>
<body>
    <main>
        <h1>Hello from Red Dwarf</h1>
        <button type="button" data-on:click="@get('/fragment')">
            Load message
        </button>
        <div id="message">Waiting…</div>
    </main>
</body>
</html>""")


@rd.get("/fragment")
async def fragment(request):
    # A Datastar action receiving text/html morphs the returned elements.
    return rd.html('<div id="message">Hello from the backend.</div>')


if __name__ == "__main__":
    rd.run(reload=True)  # Development only
```

Run the app with Python 3.11+. `reload=True` is for development; do not use it as the production process manager.

## 3. Red Dwarf API and runtime model

### Routes

Register async handlers with decorators:

```python
@rd.get("/items")
async def list_items(request):
    ...

@rd.post("/items")
async def create_item(request):
    ...

@rd.put("/items/<item_id>")
async def replace_item(request):
    ...

@rd.delete("/items/<item_id>")
async def delete_item(request):
    ...
```

Supported methods in the supplied docs are `GET`, `POST`, `PUT`, and `DELETE`.

Route parameters use one path segment each. For `/books/<book_id>`, `/books/42` gives `request.params["book_id"] == "42"`. Do not assume `<_>` or a named parameter captures multiple path segments. The router is a linear first-match scan. A known path with the wrong HTTP method may produce a `404`, not `405`.

### Request data

Use the request fields that match the input's location:

| Field              | Meaning                                                      |
| ------------------ | ------------------------------------------------------------ |
| `request.method`   | HTTP method, such as `GET` or `POST`                         |
| `request.raw_path` | Original path including query string                         |
| `request.path`     | Decoded path without query string                            |
| `request.params`   | Route parameters                                             |
| `request.query`    | Query parameters; values are lists                           |
| `request.headers`  | Lowercase header names                                       |
| `request.cookies`  | Parsed cookies                                               |
| `request.body`     | Raw request body bytes                                       |
| `request.signals`  | Parsed Datastar signals, when a Datastar request is detected |

Example:

```python
@rd.get("/books/<book_id>")
async def show_book(request):
    book_id = request.params["book_id"]
    page_values = request.query.get("page", ["1"])
    page = page_values[0]
    ...
```

Datastar sends all non-local signals by default. For a `GET` request they are sent in the `datastar` query parameter; for other methods they are sent in the JSON request body. Signals whose names begin with `_` are local to the browser and are not sent by default. Red Dwarf only parses signals when the `datastar-request` header is present. Its documented parser reads the `datastar` query parameter for `GET`/`DELETE`, and JSON from the body for other methods.

Treat `request.signals` as untrusted input. Validate shape, types, ranges, ownership, authorization, and business rules on the server. A client can edit signal values before sending them.

### Before-request hooks

`before_request` hooks are synchronous functions. Returning a `Response` short-circuits route handling:

```python
from rd import before_request


@before_request
def require_session(request):
    if not request.cookies.get("session_id"):
        return rd.redirect("/")
```

Use hooks for small synchronous checks. Do not put blocking I/O or long-running work in them. Keep authorization checks close to the command/query as well when resource-specific permissions are involved.

### Responses

| Helper                                    | Use                                                          |
| ----------------------------------------- | ------------------------------------------------------------ |
| `rd.html(body, headers=..., cookies=...)` | HTML response, normally `200`                                |
| `rd.empty()`                              | Empty `204` response; ideal for CQRS commands                |
| `rd.redirect(path)`                       | `307` redirect                                               |
| `rd.patch(html)`                          | Datastar element-patch event yielded from an async generator |

`rd.html(...)` can receive extra headers and a cookie dictionary. The documented cookie helper applies `Secure`, `HttpOnly`, `SameSite=Lax`, and `Path=/` defaults. This is a good baseline when the site is served over HTTPS through the reverse proxy.

A normal anchor navigation should return a full HTML page or a redirect. A Datastar action can receive HTML and have Datastar morph the returned elements into the existing DOM. Use `rd.empty()` when the command's result will arrive through a separate read stream.

### Request parsing and implementation limits

The supplied Red Dwarf implementation is intentionally defensive: request line and individual header lines are capped at 8 KiB, body size is capped at 1 MiB, duplicate `Content-Length` is rejected, chunked transfer encoding is rejected, and malformed header lines are skipped. Other duplicate headers are overwritten. A parse failure becomes a `400`.

Static files are served from `./static`. The resolved path must remain inside that directory, preventing parent-directory traversal and symlink escapes. Explicit MIME mappings are registered for JavaScript, CSS, and SVG. ETags use modification time and file size; `If-None-Match` can produce `304`.

## 4. Datastar defaults and conventions

Follow the Tao of Datastar unless a concrete requirement justifies a deviation.

### Backend owns application state

Store canonical state in the backend (or its database). The browser is an interactive projection of that state. The server decides what the user can do next by patching HTML and, where supported, signals.

### Start with default morphing

Datastar morphs HTML by matching elements, particularly stable IDs. Morphing preserves unchanged DOM state and reapplies changed `data-*` attributes. This is the preferred strategy for most screens.

- Give every patch target a stable, unique `id`.
- Give nested interactive elements stable IDs when they need to retain focus, event state, or transitions.
- Return the same target element in each patch.
- Prefer a larger coherent HTML fragment (“fat morph”) over hand-maintaining many tiny client-side DOM operations.
- Use `data-ignore-morph` only for a subtree that must not be morphed.

### Use signals sparingly

Good uses:

- Input fields and forms using `data-bind`.
- Temporary UI state such as a locally open menu or selected tab.
- Small derived values using `data-computed`.
- Request status indicators.

Avoid treating signals as the canonical copy of records, permissions, totals, or other backend-owned state. Do not expose secrets in signals.

### Keep expressions declarative

Common attributes:

```html
<input data-bind:display-name />
<span data-text="$displayName"></span>

<button data-show="$displayName != ''" style="display: none">Save</button>

<button data-class:active="$menuOpen">Toggle</button>
```

Use `data-on:*` for simple event handling and Datastar actions:

```html
<button data-on:click="@post('/commands/save')">Save</button>
```

Multiple Datastar statements must be separated with semicolons; a line break alone does not separate statements.

Use `data-indicator` for ordinary short requests:

```html
<button
  data-on:click="@post('/commands/save')"
  data-indicator:saving
  data-attr:disabled="$saving"
>
  Save
  <span data-show="$saving">Saving…</span>
</button>
```

If `data-indicator` is used on the same element as `data-init`, create the indicator signal before initialization, for example:

```html
<div data-indicator:connecting data-init="@get('/read/updates')"></div>
```

### Backend requests and signals

Datastar provides `@get()`, `@post()`, `@put()`, `@patch()`, and `@delete()` actions. Red Dwarf's supplied route decorators expose `GET`, `POST`, `PUT`, and `DELETE`; do not assume a `PATCH` route exists unless the repository's actual `rd.py` confirms it.

Signals are sent with backend requests by default, except local names beginning with `_`. Prefer `data-bind` for form inputs and read validated values from `request.signals`.

### Navigation

Use ordinary `<a href="...">` links for page navigation. Use `rd.redirect(...)` when the backend redirects. Let the browser own its history; do not build a client-side router for a normal Red Dwarf app.

### Backend templates

Keep repeated HTML in Python rendering functions or the project's existing template mechanism. Escape dynamic values at the output context. Avoid duplicating the same component markup across route handlers.

## 5. Preferred architecture: CQRS with a long-lived SSE read stream

Use this pattern for dashboards, counters, collaborative lists, notifications, live status, and similar reactive screens.

1. The page returns a small shell.
2. A `data-init` expression opens one long-lived `GET` request.
3. The read endpoint is an async generator. It subscribes to updates and yields `rd.patch(...)` fragments.
4. Buttons/forms send short-lived commands with `@post(...)`, `@put(...)`, or `@delete(...)`.
5. A command validates the request, changes canonical backend state, publishes an update, then returns `rd.empty()`.
6. The stream—not the command response—renders the confirmed new state into the DOM.

### Minimal in-process example

This complete example demonstrates one shared counter. It intentionally uses in-memory state for clarity; replace it with a database and shared pub/sub for durable or multi-process deployments.

```python
import asyncio
import rd


class CounterRoom:
    def __init__(self):
        self.value = 0
        self.subscribers = set()

    def render(self):
        # The value is numeric and generated by the server, not user HTML.
        return f'''<main id="counter">
    <h1>Shared counter</h1>
    <p class="count">{self.value}</p>
    <button
        id="increment"
        type="button"
        data-on:click="el.classList.add('loading'); @post('/commands/increment')"
    >
        Increment
        <span class="loading-label">Saving…</span>
    </button>
</main>'''

    def publish(self):
        # Keep at most the latest pending snapshot per subscriber. This avoids
        # an unbounded queue if a client cannot consume updates quickly enough.
        snapshot = self.render()
        for queue in tuple(self.subscribers):
            try:
                queue.put_nowait(snapshot)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                queue.put_nowait(snapshot)

    async def subscribe(self):
        queue = asyncio.Queue(maxsize=1)
        self.subscribers.add(queue)
        try:
            # Subscribe before yielding the initial snapshot. There is no await
            # between registration and this yield, so same-loop commands cannot
            # slip into a gap before the subscription exists.
            yield self.render()
            while True:
                yield await queue.get()
        finally:
            # Red Dwarf closes async generators on disconnect; this removes the
            # queue when the browser/proxy closes the SSE connection.
            self.subscribers.discard(queue)


room = CounterRoom()


@rd.get("/")
async def home(request):
    return rd.html("""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Live counter</title>
    <script type="module" src="/static/datastar.js"></script>
    <style>
        .loading-label { display: none; }
        .loading .loading-label { display: inline; }
    </style>
</head>
<body>
    <main id="counter" data-init="@get('/read/counter')">
        <p>Connecting to the live counter…</p>
    </main>
</body>
</html>""")


@rd.get("/read/counter")
async def read_counter(request):
    async for fragment in room.subscribe():
        yield rd.patch(fragment)


@rd.post("/commands/increment")
async def increment(request):
    # Authenticate/authorize and validate before mutating state in a real app.
    room.value += 1
    room.publish()
    return rd.empty()


if __name__ == "__main__":
    rd.run(reload=True)
```

The initial shell and every stream update use `id="counter"`. Datastar's default morph updates that element. The button adds a temporary `loading` class while the command is in flight; the next server-rendered snapshot removes it. This follows the Datastar Tao's CQRS loading guidance: in a CQRS screen, the command's empty response can finish before the stream update arrives, so a request-scoped `data-indicator` is not always the right signal for “the state update has been received.”

### Production rules for this pattern

- **Commit before publishing.** When using a database, commit the transaction first, then publish the resulting state/event. Never announce success before the write succeeds.
- **Publish authoritative state.** Prefer rendering the new snapshot from committed state instead of asking the browser to calculate the result.
- **Subscribe before the initial snapshot.** Avoid a gap where a write happens after the snapshot is read but before the subscriber is registered.
- **Clean up subscriptions.** Use `try/finally` in async generators. Red Dwarf wraps stream generators with `aclosing`, so generator cleanup runs on disconnect.
- **Bound per-client queues.** Coalesce stale snapshots when latest-state rendering is sufficient. Use a durable event log or a different delivery design if every intermediate event must be processed.
- **Scope by user or tenant.** Do not broadcast private records to a process-wide topic. Authorize the stream and each command independently.
- **Plan for reconnects.** A newly connected stream should be able to reconstruct current state from the backend before waiting for future events.
- **Use shared infrastructure across processes.** An in-memory Python set/queue only reaches subscribers in this process. Multi-worker or multi-instance deployments need a shared broker/pub-sub mechanism and durable canonical storage.
- **Handle command failures.** If a command fails, do not publish a success state. Return an appropriate error response or publish an explicit error state through the read model so a CQRS loading treatment can be cleared.

### Forms and command payloads

Bind fields to signals, submit with a Datastar action, then validate on the server:

```html
<div>
  <label>
    New name
    <input data-bind:name />
  </label>
  <button type="button" data-on:click="@post('/commands/rename')">
    Rename
  </button>
</div>
```

```python
@rd.post("/commands/rename")
async def rename(request):
    raw_name = request.signals.get("name", "")
    if not isinstance(raw_name, str):
        return rd.empty()  # Replace with the app's explicit validation response.

    name = raw_name.strip()
    if not name or len(name) > 80:
        # A real app should publish/render a validation error for this form.
        return rd.empty()

    # Persist the validated value, then publish an updated view to subscribers.
    # Store the plain value; escape it only when rendering HTML.
    return rd.empty()
```

The snippet shows where the data enters the application; it is not a complete validation UX. Add an explicit error/read-model path rather than silently swallowing invalid commands in a real feature.

## 6. Rocket: reusable components with props down, events up

Use Rocket when a control has an independent public API, encapsulated internal state, or non-trivial browser integration. Keep page-level business state on the backend and keep component internals inside the component.

### When to use what

- **Datastar attributes:** simple bindings, toggles, visibility, classes, request actions, and small derived values.
- **Rocket props:** values that a parent/page should set on the component, such as `title`, `value`, `busy`, `theme`, or a selected record ID.
- **Rocket local signals (`$$`):** component-private interaction state, such as a copied flag, local animation phase, or internal selection state.
- **Rocket `setup` / `effect` / `cleanup`:** timers, subscriptions, observers, third-party widgets, and lifecycle work.
- **Rocket `observeProps(...)`:** synchronize an external widget or imperative API when backend-patched props change.
- **Rocket custom events:** notify the parent that the user interacted with the component. The parent decides what command or application behavior follows.

Do not move a whole application's state into Rocket-local signals. Do not put simple page-owned behavior inside a component merely because Rocket is available.

### Load the Rocket bundle

Use the Rocket bundle instead of the Datastar-only bundle:

```html
<script type="module" src="/static/datastar-rocket.js"></script>
<script type="module" src="/static/components/status-card.js"></script>
```

### Define a component with public props

`static/components/status-card.js`:

```javascript
import { rocket } from "/static/datastar-rocket.js";

rocket("app-status-card", {
  mode: "light",
  props: ({ string, number, bool }) => ({
    label: string.trim.default("Status"),
    value: number.min(0).default(0),
    busy: bool.default(false),
  }),
  render: ({ html, props: { label, value, busy } }) => html`
    <article class="status-card">
      <h2>${label}</h2>
      <strong>${value}</strong>
      <p data-show="${busy}">Updating…</p>
    </article>
  `,
});
```

Use it in server-rendered HTML:

```html
<app-status-card
  id="pending-status"
  label="Pending jobs"
  value="12"
  busy="false"
></app-status-card>
```

Rocket props are declared with codecs. Rocket decodes initial attributes, observes subsequent attribute changes, and exposes normalized prop values to `setup` and `render`. JavaScript-style prop names map to kebab-case attributes (for example `startDate` maps to `start-date`).

### Update Rocket props from an SSE HTML patch

This is the preferred Red Dwarf + Rocket integration for backend-owned component state:

1. The stream yields HTML containing the same Rocket custom-element tag and the same stable host ID.
2. The patch changes the host's public attributes, for example `value="12"` to `value="13"`.
3. Datastar morphs the existing host element and applies the changed attributes.
4. Rocket observes the attribute changes, decodes the new prop values, and rerenders the component. By default, `renderOnPropChange` is enabled.

For example, the server can yield this fragment after the backend state changes:

```html
<main id="dashboard">
  <app-status-card
    id="pending-status"
    label="Pending jobs"
    value="13"
    busy="false"
  ></app-status-card>
</main>
```

The preceding version should use the same `main#dashboard` and `app-status-card#pending-status` IDs. Keep the Rocket tag and host ID stable; update attributes to update public props. Do not replace the component with a different tag or invent a separate frontend copy of the backend state.

This works because Rocket props are reflected through observed HTML attributes. The default behavior is to queue a render after prop changes; multiple changes in the same turn are coalesced. `observeProps(...)` listeners are notified as the decoded props change.

### Use `observeProps` for imperative integrations

When a component wraps a charting library or another imperative widget, disable automatic component rerendering and synchronize the widget from prop changes:

```javascript
rocket("app-sparkline", {
  mode: "light",
  props: ({ json, string }) => ({
    series: json.default(() => []),
    theme: string.default("light"),
  }),
  renderOnPropChange: false,
  setup: ({ host, props, observeProps }) => {
    observeProps(
      (nextProps, changes) => {
        // updateChart is an app-owned integration function.
        updateChart(host, nextProps.series, nextProps.theme, changes);
      },
      "series",
      "theme",
    );
  },
  render: ({ html }) => html`<canvas width="640" height="320"></canvas>`,
});
```

Use `onFirstRender(...)` instead of `setup(...)` if initialization needs rendered elements or `data-ref:*` handles. `setup` runs before the initial render/apply pass; `onFirstRender` runs after refs have been populated. Register cleanup for timers, observers, subscriptions, and imperative widget instances.

### Events up

A component should expose a public event rather than directly deciding application-level behavior. Rocket's manifest can document that event:

```javascript
rocket("app-confirm-button", {
  manifest: {
    events: [
      {
        name: "confirm",
        kind: "custom-event",
        bubbles: true,
        composed: true,
        description: "The user confirmed the action.",
      },
    ],
  },
  setup: ({ host, action }) => {
    action("confirm", () => {
      host.dispatchEvent(
        new CustomEvent("confirm", {
          bubbles: true,
          composed: true,
        }),
      );
    });
  },
  render: ({ html }) => html`
    <button type="button" data-on:click="@confirm()">Confirm</button>
  `,
});
```

The parent handles the event and decides what command to send:

```html
<app-confirm-button
  data-on:confirm="@post('/commands/confirm')"
></app-confirm-button>
```

Use `bubbles: true` so ancestors can listen, and `composed: true` when the event needs to cross a shadow-DOM boundary. Keep the event payload small and non-sensitive; the server must still authorize and validate the resulting command.

### Rocket design rules

- Prefer public props for values that a page author or parent should set.
- Prefer `$$` for private component state.
- Prefer plain Datastar expressions for simple local interactions; use a named Rocket `action(...)` when imperative work needs a reusable entry point.
- Keep `setup` for work that does not need rendered refs; use `onFirstRender` for ref-backed setup.
- Use CSS custom properties for theming across shadow boundaries.
- Default to Rocket's normal rendering behavior. Set `renderOnPropChange: false` only when a deliberate imperative update path such as `observeProps` replaces rerendering.
- Do not use Rocket's manual `render(...)` calls as a second fine-grained state system. Prefer signals and Datastar's existing reactive relationships for state that changes over time.
- Keep component host IDs stable so backend HTML morphs update the existing component instance.

## 7. Red Dwarf + Datastar capability boundary

Datastar's full protocol supports more than the supplied Red Dwarf helper exposes. Keep these distinctions clear:

| Capability                                                        | Datastar                      | Red Dwarf helper described here                   |
| ----------------------------------------------------------------- | ----------------------------- | ------------------------------------------------- |
| Patch HTML elements                                               | Yes                           | Yes, via `rd.patch(html)`                         |
| Patch signals with `datastar-patch-signals`                       | Yes                           | No first-class helper documented                  |
| Patch element selector/mode options (append, inner, remove, etc.) | Yes                           | Not exposed by `rd.patch(html)`                   |
| Event IDs and retry settings                                      | SSE can support these         | Not exposed by the described helper               |
| Stream an async generator                                         | Backend integration dependent | Yes; handler async generators are streamed as SSE |
| Multiple events over one stream                                   | Yes                           | Repeated `yield rd.patch(...)` element events     |

Therefore:

- Use `rd.patch(...)` for HTML element morphs.
- Put transient interaction state in browser signals when useful, but send canonical data changes through commands and reflect confirmed state with HTML patches.
- Do not write code that assumes `yield rd.patch_signals(...)`, selector/mode arguments, or event IDs exist.
- If a feature genuinely requires a Datastar SSE event Red Dwarf cannot express, inspect the actual Red Dwarf source and deliberately extend/replace the SSE helper; do not quietly fake the API in application code.

## 8. Security requirements

1. **Escape dynamic HTML.** Use context-appropriate escaping for text and attributes. In Python, `html.escape(value, quote=True)` is a useful HTML escaping primitive for text/attribute values, but it is not a universal sanitizer for URLs, CSS, JavaScript, or arbitrary HTML.
2. **Keep Datastar expressions static.** Never concatenate user input into `data-on:*`, `data-init`, or another executable expression attribute.
3. **Treat signals as attacker-controlled.** Signals are visible in the page, can be modified by the user, and are sent back with backend requests. Never put credentials, secrets, or trusted authorization decisions in signals.
4. **Validate server-side.** Check types, lengths, numeric bounds, allowed values, ownership, and authorization for every command and protected read.
5. **Sanitize user HTML.** If the product intentionally allows rich user-provided HTML, use an HTML sanitizer suited to that requirement. Escaping and `data-ignore` are not substitutes for a sanitizer when rendering allowed HTML.
6. **Understand CSP.** Datastar's default expression evaluation uses the `Function()` constructor, which ordinarily requires `unsafe-eval` in `script-src`. For a stricter policy, use Datastar CSP mode: generate a cryptographically secure nonce for every full-page response, put it in the root `<html data-nonce="...">`, and include the matching nonce in the CSP `script-src`. CSP mode does not sanitize untrusted expressions or HTML.
7. **Protect cookies and sessions.** Use HTTPS at the reverse proxy. Keep session identifiers out of signals and URLs. Enforce authorization on the server; the existence of a cookie is not proof that a requested resource is allowed.
8. **Do not trust hidden UI.** `data-show`, disabled buttons, and hidden controls are presentation only. Commands must enforce the same constraints independently.

For CSP nonce mode, follow the current Datastar reference carefully. The nonce must be unique/cryptographically secure per full-page response and must match the policy. Do not hard-code a development nonce into production templates.

## 9. Deployment and operational guidance

- Run Red Dwarf behind a reverse proxy such as the Caddy deployment described in the Red Dwarf notes.
- Keep the application bound to loopback or a protected Unix socket when the proxy is on the same host. Do not expose the bare HTTP server directly to the public internet.
- Ensure the proxy forwards long-lived `text/event-stream` responses without buffering them until completion and uses suitable upstream/read timeouts for the application's stream lifetime.
- Expect the Red Dwarf SSE implementation to close the connection when the generator finishes or the client disconnects. The documented stream response uses `Connection: close`.
- Use `rd.run(reload=True)` only during development. Use the deployment's process manager to supervise the application in production.
- The built-in server does not implement TLS, compression, HTTP/2, or advanced slow-client defenses. Delegate edge concerns to the reverse proxy and deployment platform.
- Datastar's Tao recommends considering stream compression because HTML morph payloads compress well. Red Dwarf does not provide compression itself; configure it at the proxy only after verifying that streaming remains incremental.
- Keep static assets local and versioned. Avoid making page interactivity depend on an unpinned external CDN at runtime.

## 10. Testing and review checklist

Before considering a feature complete, check:

### HTTP and routing

- [ ] Routes use only methods supported by the repository's Red Dwarf version.
- [ ] Route parameters are single path segments; query values are handled as lists.
- [ ] Invalid or missing request data is handled explicitly.
- [ ] Authorization is enforced on both read streams and commands.
- [ ] No feature depends on a `405` response unless the router has been extended to provide it.

### Datastar and HTML

- [ ] Every patched root has a stable ID present in the initial DOM.
- [ ] Repeated/nested patch targets that need state preservation have stable IDs.
- [ ] HTML is rendered from backend state and dynamic values are escaped.
- [ ] Datastar expressions are static and contain no untrusted interpolated code.
- [ ] Signals contain only transient input/UI state, not secrets or canonical business data.
- [ ] Page navigation uses anchors or backend redirects rather than a custom client router.

### CQRS and SSE

- [ ] The read shell starts its stream with `data-init`.
- [ ] The stream sends an initial snapshot and subsequent updates.
- [ ] The subscription exists before its initial snapshot is yielded, avoiding a lost-update window.
- [ ] Commands validate, persist/commit, publish, then return `rd.empty()`.
- [ ] Stream subscriptions clean up in `finally` on disconnect.
- [ ] Per-client queues are bounded or otherwise protected from unbounded growth.
- [ ] User/tenant channels are isolated; private data is never broadcast globally.
- [ ] A reconnect can rebuild the current view from canonical state.
- [ ] A test or manual check confirms that the UI only displays success after backend confirmation.

### Rocket

- [ ] Rocket is loaded with `datastar-rocket.js`, not alongside a second Datastar bundle.
- [ ] Public component inputs are declared as props with appropriate codecs/defaults.
- [ ] Component instances and patch targets keep stable host IDs.
- [ ] SSE HTML patches update host attributes to change props.
- [ ] Internal state stays local to the component; parent-owned state stays in the parent/backend.
- [ ] Custom events are documented and bubble/compose as required.
- [ ] Setup resources are cleaned up when the component disconnects.

### Deployment and security

- [ ] The proxy streams SSE incrementally and its timeouts support long-lived connections.
- [ ] The app is not exposed directly to untrusted networks.
- [ ] Session and authorization checks are performed server-side.
- [ ] User-controlled HTML, attributes, and URL values use context-appropriate handling.
- [ ] CSP is intentionally configured for the selected Datastar evaluation mode.
- [ ] Production does not run with `reload=True`.

## 11. Useful Datastar references

Use these links when a task needs more detail than this quickstart provides:

- [Datastar documentation](https://data-star.dev/docs)
- [The Tao of Datastar](https://data-star.dev/guide/the_tao_of_datastar)
- [Attributes reference](https://data-star.dev/reference/attributes)
- [Backend actions reference](https://data-star.dev/reference/actions#backend-actions)
- [SSE events reference](https://data-star.dev/reference/sse_events)
- [Rocket reference](https://data-star.dev/reference/rocket)
- [Rocket Flow example](https://data-star.dev/examples/rocket_flow)
- [Datastar Inspector](https://data-star.dev/pro#datastar-inspector)

---

## Agent's default decision rule

When implementing a new interactive feature, start by asking:

1. What is the canonical backend state?
2. What HTML fragment represents the current state, and what stable ID will Datastar morph?
3. Can one `data-init` read stream deliver initial state and all later updates?
4. Can writes be short commands that validate, commit, publish, and return `rd.empty()`?
5. Is the UI behavior simple enough for Datastar attributes, or does it deserve a Rocket component with public props and events?

Prefer the smallest solution that answers those questions. Do not introduce a client-side state store, custom router, or general-purpose frontend framework unless the requirements demonstrate a real need.

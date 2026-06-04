import grug as rd
from pprint import pprint

# import redwarf as rd
# @rd.get("/")
# rd.run()
# 1 seul objet stateful la request, tout le reste en fonctionnel
# non app doit être stateful pour au moins avoir les routes non? bof en vrai, quand tu call run
# no import
# async


@rd.get("/")
async def index(request):
    response = rd.html("""
<html lang="en">
<head>
    <meta charset="UTF-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
	<link rel="icon" href="/static/img/red_dwarf.png"/>
    <link rel="stylesheet" href="/static/css/index.css"/>
	<script type="module" src="/static/js/datastar.js"></script>
</head>
<body class="gc">
    <h1 class="gt-xl">red dwarf</h1>
    <p>small and capable</p>
    <img src="/static/img/red_dwarf.png"/>
    <p>Type to see your grug name</p>
    <input type=text name=name data-bind:name data-on:input="@post('/club')"></input>
    <div>Your grug name is <p id=username></p></div>
</body>
</html>
""", headers=[rd.cookie("nusky", "vaati")])
    pprint(response)
    return response


@rd.post("/club")
async def smash_club(request):
    name = request.signals.get("name")
    if name:
        # we should use html.escape one day
        return rd.html(f"<p id=username>GRUG {name}</p>")
    else:
        return rd.empty()

@rd.get("/sse")
async def sse(request):
    return rd.html("""
<html lang="en">
<head>
    <meta charset="UTF-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
	<link rel="icon" href="/static/img/red_dwarf.png"/>
    <link rel="stylesheet" href="/static/css/index.css"/>
	<script type="module" src="/static/js/datastar.js"></script>
</head>
<body class="gc">
    <div style="
    width: 100%;
    height: 100%;
">
        <svg viewBox="0 0 100 100">
            <circle x=50 y=50 r=10 fill="red">
        </svg>
    </div>
    <main id="main" data-init="@get('/sse_stream')">waiting for a stream</main>
</body>
</html>
""")

@rd.get("/sse_stream")
async def sse_stream(request):
    response = rd.patch("""
<main id="main">got it got it</main>
""")
    pprint(response)
    return response

if __name__ == "__main__":
    rd.run(reload=True)
    # app.run(sock="/tmp/grug.sock")

# viande out

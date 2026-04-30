import grug as rd

# import redwarf as rd
# @rd.get("/")
# rd.run()
# 1 seul objet stateful la request, tout le reste en fonctionnel
# non app doit être stateful pour au moins avoir les routes non? bof en vrai, quand tu call run
# no import
# async


@rd.get("/")
def index(request):
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
    <h1 class="gt-xl">red dwarf</h1>
    <img src="/static/img/red_dwarf.png"/>
    <p>Type to see your grug name</p>
    <input type=text name=name data-bind:name data-on:input="@post('/club')"></input>
    <div>Your grug name is <p id=username></p></div>
</body>
</html>
""")


@rd.post("/club")
async def smash_club(request):
    name = request.signals.get("name")
    if name:
        # we should use html.escape one day
        return rd.html(f"<p id=username>GRUG {name}</p>")
    else:
        return rd.empty()


if __name__ == "__main__":
    rd.run(reload=True)
    # app.run(sock="/tmp/grug.sock")

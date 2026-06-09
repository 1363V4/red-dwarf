import reddwarf as rd


@rd.get("/hello")
async def hello(request):
    return rd.html(
'''
hello
'''
    )
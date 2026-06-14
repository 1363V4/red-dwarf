import reddwarf as rd


@rd.get("/hello")
async def hello(request):
    print("ZIZI")
    return rd.html(
        """
hello
"""
    )

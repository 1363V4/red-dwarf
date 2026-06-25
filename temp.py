from http import cookies

c = cookies.SimpleCookie()
c['a'] = 1
c['b'] = 2

c = cookies.SimpleCookie('cbs=bd; down=0; laid=up',)
print(c)

for x, y in c.items():
    print(x, y)
    print(x, y.value)
    print(x, type(x))
    print(y, type(y))

# import re

# path_pattern = "/<_>"

# segments = re.split(r"(<[^>]+>)", path_pattern)
# print("segments:", segments)
# regex = ""
# for seg in segments:
#     if seg.startswith("<") and seg.endswith(">"):
#         name = seg[1:-1]
#         regex += f"(?P<{name}>[^/]+)"
#     else:
#         regex += re.escape(seg)  # escapes '/' and literal text safely
# pattern = re.compile(f"^{regex}$")
# print("pattern", pattern)

# x = "".encode('utf-8')
# print(x)

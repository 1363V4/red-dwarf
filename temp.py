import re

path_pattern = "/<_>"

segments = re.split(r"(<[^>]+>)", path_pattern)
print("segments:", segments)
regex = ""
for seg in segments:
    if seg.startswith("<") and seg.endswith(">"):
        name = seg[1:-1]
        regex += f"(?P<{name}>[^/]+)"
    else:
        regex += re.escape(seg)  # escapes '/' and literal text safely
pattern = re.compile(f"^{regex}$")
print("pattern", pattern)

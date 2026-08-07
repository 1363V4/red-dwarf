from pathlib import Path

_SITE_DIR = Path(__file__).resolve().parent
_HTML_DIR = _SITE_DIR / "static" / "html"
_ESSAYS_DIR = _HTML_DIR / "essays"

_html_parts = {}

for html_part in _HTML_DIR.glob("*.html"):
    with open(html_part, "r", encoding="utf8") as f:
        _html_parts[html_part.stem.upper()] = f.read()

for html_part in _ESSAYS_DIR.glob("*.html"):
    with open(html_part, "r", encoding="utf8") as f:
        _html_parts["ESSAY_" + html_part.stem.upper()] = f.read()

def _base_template(main):
    return f'''
<!doctype html>
<html lang="en">
    {_html_parts['HEAD']}
    {_html_parts['HEADER']}
    {main}
    {_html_parts['FOOTER']}
</html>
'''

PAGE_INDEX = _base_template(_html_parts['MAIN_INDEX'])
PAGE_ESSAYS = _base_template(_html_parts['MAIN_ESSAYS'])
PAGE_EXAMPLES = _base_template(_html_parts['MAIN_EXAMPLES'])
PAGE_FAQ = _base_template(_html_parts['MAIN_FAQ'])
PAGE_GETTING_STARTED = _base_template(_html_parts['MAIN_GETTING_STARTED'])
PAGE_RED = _base_template(_html_parts['MAIN_RED'])
PAGE_DOCS = _base_template(_html_parts['MAIN_DOCS'])

ESSAY_V0 = _base_template(_html_parts['ESSAY_V0'])
ESSAY_DATASTAR = _base_template(_html_parts['ESSAY_DATASTAR'])
ESSAY_PYTHON = _base_template(_html_parts['ESSAY_PYTHON'])
ESSAY_REAL = _base_template(_html_parts['ESSAY_REAL'])

"""HTML -> readable text, using only the standard library.

py-xiaozhi ships as an installer, so pulling in beautifulsoup/lxml/trafilatura
for this would add install weight and platform-specific wheels for something
html.parser handles adequately.
"""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

# Containers whose text is chrome, not content.
_DROP = {"script", "style", "noscript", "svg", "canvas", "template", "head"}
# Tags that imply a line break in the extracted text.
_BLOCK = {
    "p", "div", "section", "article", "header", "footer", "br", "li", "tr",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "table", "ul", "ol",
}

_WS = re.compile(r"[ \t\f\v]+")
_NL = re.compile(r"\n{3,}")


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._out: list[str] = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in _DROP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BLOCK:
            self._out.append("\n")

    def handle_endtag(self, tag):
        if tag in _DROP:
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in _BLOCK:
            self._out.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
            return
        if data.strip():
            self._out.append(data)

    def text(self) -> str:
        raw = "".join(self._out)
        raw = _WS.sub(" ", raw)
        raw = "\n".join(line.strip() for line in raw.split("\n"))
        return _NL.sub("\n\n", raw).strip()


def html_to_text(html: str) -> tuple[str, str]:
    """Return (title, text). Never raises on malformed markup."""
    p = _Extractor()
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    return unescape(p.title).strip(), p.text()


def strip_tags(fragment: str) -> str:
    """Flatten a small HTML fragment (a search snippet) to plain text."""
    return unescape(re.sub(r"<[^>]+>", "", fragment)).strip()

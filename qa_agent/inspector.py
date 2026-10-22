"""Fetch the target page and summarise its interactive elements so the model is grounded in real selectors."""
from html.parser import HTMLParser

import requests

KEEP_ATTRS = ("id", "name", "type", "data-testid", "href", "action", "method", "role")


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements: list[dict] = []
        self.title = ""
        self._in_title = False
        self._open: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self._in_title = True
        if tag in {"input", "button", "a", "form", "select", "textarea", "h1", "h2"} or "data-testid" in a:
            el = {"tag": tag, **{k: a[k] for k in KEEP_ATTRS if k in a}}
            self.elements.append(el)
            self._open = el

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        self._open = None

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title += text
        elif self._open is not None and "text" not in self._open:
            self._open["text"] = text


def inspect_page(url: str) -> dict:
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    c = _Collector()
    c.feed(resp.text)
    return {"url": url, "status": resp.status_code, "title": c.title, "elements": c.elements}

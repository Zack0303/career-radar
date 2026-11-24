"""Stdlib HTTP JSON transport and HTML text sanitization helpers."""

from __future__ import annotations

import html
from html.parser import HTMLParser
import json
from typing import Any, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ATSRequestError(RuntimeError):
    """Raised when an official ATS HTTP request fails or returns invalid JSON."""

    def __init__(self, message: str, *, url: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.url = url
        self.status_code = status_code


def http_json_request(
    method: str,
    url: str,
    payload: Optional[Mapping[str, Any]] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: float = 15.0,
) -> Any:
    """Execute an HTTP request returning decoded JSON using Python stdlib only."""
    req_headers: dict[str, str] = {
        "User-Agent": "career-radar/0.1 (local-first job tracker)",
        "Accept": "application/json",
    }
    if headers:
        req_headers.update(headers)

    data: Optional[bytes] = None
    if payload is not None:
        data = json.dumps(dict(payload)).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")

    request = Request(url=url, data=data, headers=req_headers, method=method.upper())
    try:
        with urlopen(request, timeout=timeout) as response:
            raw_bytes = response.read()
    except HTTPError as exc:
        body_preview = ""
        try:
            body_preview = exc.read(256).decode("utf-8", errors="replace").strip()
        except Exception:
            body_preview = ""
        detail = f": {body_preview}" if body_preview else ""
        raise ATSRequestError(
            f"HTTP {exc.code} from {url}{detail}",
            url=url,
            status_code=int(exc.code),
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ATSRequestError(f"Network error requesting {url}: {exc}", url=url) from exc

    try:
        return json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ATSRequestError(f"Invalid JSON response from {url}: {exc}", url=url) from exc


class _TextExtractor(HTMLParser):
    """Minimal HTML-to-plain-text parser preserving block line breaks."""

    _BLOCK_TAGS = frozenset({"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.lower() == "li":
            self._parts.append("\n- ")
        elif tag.lower() in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        lines = [" ".join(line.split()) for line in "".join(self._parts).splitlines()]
        non_empty = [line for line in lines if line]
        return "\n".join(non_empty)


def strip_html(raw: str) -> str:
    """Unescape HTML entities (handling double-escaped Greenhouse content) and strip tags."""
    if not raw or not raw.strip():
        return ""
    unescaped = html.unescape(raw)
    if "<" not in unescaped and "&lt;" in raw:
        unescaped = html.unescape(unescaped)
    # Greenhouse frequently returns HTML-escaped HTML (`&lt;p&gt;...&lt;/p&gt;`),
    # so running a second unescape when `&lt;`/`&gt;` remained ensures tags parse cleanly.
    if "&lt;" in unescaped or "&gt;" in unescaped:
        unescaped = html.unescape(unescaped)
    parser = _TextExtractor()
    parser.feed(unescaped)
    parser.close()
    return parser.get_text()

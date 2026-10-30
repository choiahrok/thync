"""Notion pages edited recently, through the Notion API (POST /v1/search, which only reads).

The token of a Notion internal integration comes from NOTION_TOKEN or STATE_DIR/notion_token. The integration
sees only the pages shared with it. With `notion_user_id` in the config, only pages last edited by that user count.
"""
import json
import os
import time
import urllib.request

from ..config import NOTION_USER, REVIEW_TTL_SEC, STATE_DIR
from .jira import _open

API = "https://api.notion.com/v1/search"
VERSION = "2022-06-28"

_pages: tuple[float, list] = (0.0, [])


def _token() -> str:
    token = os.environ.get("NOTION_TOKEN", "")
    if not token and (STATE_DIR / "notion_token").is_file():
        token = (STATE_DIR / "notion_token").read_text().strip()
    return token


def parse(results: list, user: str = "") -> list[dict]:
    """Search results -> {id, title, url, at}. Pages without a title are skipped."""
    out = []
    for p in results:
        if p.get("object") != "page" or (user and (p.get("last_edited_by") or {}).get("id") != user):
            continue
        prop = next((v for v in (p.get("properties") or {}).values() if v.get("type") == "title"), {})
        title = "".join(t.get("plain_text", "") for t in prop.get("title") or []).strip()
        if title:
            out.append({"id": p["id"], "title": title, "url": p.get("url", ""), "at": p["last_edited_time"]})
    return out


def search(token: str, pages: int = 1) -> list:
    """Newest edited pages first, up to `pages` x 100 results."""
    results, cursor = [], None
    for _ in range(pages):
        body = {"filter": {"property": "object", "value": "page"}, "page_size": 100,
                "sort": {"direction": "descending", "timestamp": "last_edited_time"}}
        if cursor:
            body["start_cursor"] = cursor
        req = urllib.request.Request(API, data=json.dumps(body).encode(), method="POST", headers={
            "Authorization": f"Bearer {token}", "Notion-Version": VERSION, "Content-Type": "application/json"})
        with _open(req, timeout=15) as r:
            data = json.load(r)
        results += data.get("results", [])
        cursor = data.get("next_cursor")
        if not data.get("has_more") or not cursor:
            break
    return results


def recent_pages(now: float) -> list[dict]:
    global _pages
    token = _token()
    if token and now - _pages[0] > REVIEW_TTL_SEC:
        try:
            # Filtering by user drops teammates' edits, so look further back to still find mine.
            _pages = (now, parse(search(token, 3 if NOTION_USER else 1), NOTION_USER))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            _pages = (now, _pages[1])
    return _pages[1]


def refresh_forever() -> None:
    while _token():
        recent_pages(time.time())
        time.sleep(REVIEW_TTL_SEC / 2)

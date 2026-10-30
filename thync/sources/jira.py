"""Jira ticket summaries and epics, read from STATE_DIR/jira.json: {"KEY-1": {"summary", "status", "epic", "epic_summary"}}.

With `jira_email` in the config and an API token (JIRA_API_TOKEN or STATE_DIR/jira_token), refresh_forever()
fetches every key the graph has used through the Jira Cloud REST API and keeps the file current. With "jira" in
the sources it also fetches the tickets assigned to me that are in progress or recently updated, and marks them
"mine". Without a token the file is filled by hand. thync only reads from Jira.
"""
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from ..config import JIRA_BROWSE, JIRA_EMAIL, SOURCES, STATE_DIR
from ..util import read_json, write_json

JIRA_FILE = STATE_DIR / "jira.json"
BRANCH_KEY = re.compile(r"\b([A-Za-z][A-Za-z0-9]{1,9}-\d{1,6})\b")  # keys in branch names: abc-123
TITLE_KEY = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d{1,6})\b")          # keys in titles: ABC-123
REFRESH_SEC = 600
MAX_KEYS = 100
MINE_JQL = 'assignee = currentUser() AND (statusCategory = "In Progress" OR updated >= -7d) ORDER BY updated DESC'

_seen: set[str] = set()  # keys the graph asked about, so the refresh knows what to fetch


def clean(summary: str) -> str:
    """'[API][console] Audit log screen' -> 'Audit log screen'"""
    return re.sub(r"^(\[[^\]]*\]\s*)+", "", summary or "").strip() or summary


class Jira:
    def __init__(self):
        self.tickets: dict = read_json(JIRA_FILE, {})

    def _get(self, key: str) -> dict:
        if re.fullmatch(r"[A-Z][A-Z0-9]{1,9}-\d{1,6}", key) and len(_seen) < MAX_KEYS:
            _seen.add(key)
        return self.tickets.get(key, {})

    def name(self, key: str) -> str:
        """Human-readable ticket name, or the key when unknown."""
        return clean(self._get(key).get("summary", "")) or key

    def summary(self, key: str) -> str:
        return self._get(key).get("summary", key)

    def status(self, key: str) -> str:
        return self._get(key).get("status", "")

    def url(self, key: str) -> str:
        return f"{JIRA_BROWSE}{key}" if JIRA_BROWSE else ""

    def mine(self) -> dict:
        """Tickets assigned to me, as of the last refresh: key -> ticket."""
        return {k: t for k, t in self.tickets.items() if t.get("mine")}

    def unit_of(self, key: str) -> tuple[str, str]:
        """(work unit id, unit name): the epic when the ticket has one, otherwise the ticket itself."""
        t = self._get(key)
        if t.get("epic"):
            return f"epic:{t['epic']}", clean(t.get("epic_summary") or t["epic"])
        return f"jira:{key}", self.name(key)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # never carry the Authorization header to wherever a redirect points


_open = urllib.request.build_opener(_NoRedirect).open


def _auth() -> str:
    token = os.environ.get("JIRA_API_TOKEN", "")
    if not token and (STATE_DIR / "jira_token").is_file():
        token = (STATE_DIR / "jira_token").read_text().strip()
    return "Basic " + base64.b64encode(f"{JIRA_EMAIL}:{token}".encode()).decode() if JIRA_EMAIL and token else ""


def fetch(base: str, auth: str, key: str) -> dict:
    req = urllib.request.Request(f"{base}/rest/api/3/issue/{key}?fields=summary,status,parent",
                                 headers={"Authorization": auth, "Accept": "application/json"})
    with _open(req, timeout=15) as r:
        f = json.load(r)["fields"]
    return {k: v for k, v in _ticket(f).items() if k != "updated"}


def _ticket(f: dict) -> dict:
    parent = f.get("parent") or {}
    return {"summary": f["summary"], "status": f["status"]["name"], "epic": parent.get("key", ""),
            "epic_summary": (parent.get("fields") or {}).get("summary", ""), "updated": f.get("updated", "")}


def search_mine(base: str, auth: str) -> dict:
    """Tickets assigned to me that are in progress or were updated in the last 7 days: key -> ticket."""
    q = urllib.parse.urlencode({"jql": MINE_JQL, "fields": "summary,status,parent,updated", "maxResults": 50})
    req = urllib.request.Request(f"{base}/rest/api/3/search/jql?{q}",
                                 headers={"Authorization": auth, "Accept": "application/json"})
    with _open(req, timeout=15) as r:
        return {i["key"]: _ticket(i["fields"]) for i in json.load(r).get("issues", [])}


def refresh_forever() -> None:
    base, auth = JIRA_BROWSE.split("/browse/")[0].rstrip("/"), _auth()
    if not auth or not base.startswith("https://"):
        return
    fetched: dict[str, float] = {}
    mine_at = 0.0
    while True:
        wait = 60
        try:
            mine = None
            if "jira" in SOURCES and time.time() - mine_at > REFRESH_SEC / 2:
                mine_at = time.time()
                try:
                    mine = search_mine(base, auth)
                    fetched.update({k: time.time() for k in mine})  # just fetched; no need to ask again
                except urllib.error.HTTPError as e:
                    print(f"thync: Jira search failed (HTTP {e.code})", file=sys.stderr, flush=True)
                    if e.code in (401, 429) or e.code >= 500:
                        raise  # back off like the per-key fetch below
                except (OSError, ValueError, KeyError, TypeError):
                    pass
            due = [k for k in sorted(_seen) if time.time() - fetched.get(k, 0) > REFRESH_SEC]
            got = {}
            for key in due:
                try:
                    got[key] = fetch(base, auth, key)
                except urllib.error.HTTPError as e:
                    if e.code in (401, 429) or e.code >= 500:  # bad token, rate limit, outage: stop and back off
                        wait = REFRESH_SEC
                        break
                except (OSError, ValueError, KeyError, TypeError):
                    pass  # this key only (bad body, timeout); the rest still get their turn
                fetched[key] = time.time()  # a failing key waits REFRESH_SEC too, so it cannot starve the others
            if got or mine is not None:
                tickets = read_json(JIRA_FILE, {})
                tickets.update({k: {**tickets.get(k, {}), **v} for k, v in got.items()})
                if mine is not None:
                    tickets = {k: {**t, "mine": False} for k, t in tickets.items()}
                    tickets.update({k: {**tickets.get(k, {}), **v, "mine": True} for k, v in mine.items()})
                write_json(JIRA_FILE, tickets)
        except Exception:  # noqa: BLE001 — the thread must keep running; the next pass tries again
            wait = REFRESH_SEC
        time.sleep(wait)

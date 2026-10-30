"""GitHub through the `gh` CLI: review requests to me, my open PRs waiting on review, and my recent commits.

Both calls take a few seconds, so refresh_forever() keeps the cache warm in a background thread and
requests never wait on GitHub.
"""
import functools
import json
import subprocess
import time

from ..config import MAX_DAYS, REVIEW_TTL_SEC

_reviews: tuple[float, list] = (0.0, [])
_sent: tuple[float, list] = (0.0, [])
_commits: tuple[float, list] = (0.0, [])
MAX_BRANCHES = 20  # pushed branches whose head commit message is fetched

SENT_QUERY = """query { search(query:"is:open is:pr author:@me archived:false", type:ISSUE, first:50) { nodes { ... on PullRequest {
  title url number updatedAt isDraft repository { name } reviewDecision
  reviewRequests(first:5) { nodes { requestedReviewer { ... on User { login } ... on Team { name } } } }
  latestReviews(first:10) { nodes { author { login } state } } } } } }"""


def review_requests(now: float) -> list[dict]:
    """Open PRs where my review is requested (search API items)."""
    global _reviews
    if now - _reviews[0] > REVIEW_TTL_SEC:
        try:
            out = subprocess.run(
                ["gh", "api", "-X", "GET", "search/issues", "-f", "q=is:open is:pr review-requested:@me archived:false",
                 "-f", "per_page=30"], capture_output=True, text=True, timeout=20, check=True).stdout
            _reviews = (now, json.loads(out).get("items", []))
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError):
            _reviews = (now, _reviews[1])
    return _reviews[1]


def sent_reviews(now: float) -> list[dict]:
    """My open, non-draft PRs that have a pending review request or any review."""
    global _sent
    if now - _sent[0] > REVIEW_TTL_SEC:
        try:
            out = subprocess.run(["gh", "api", "graphql", "-f", f"query={SENT_QUERY}"],
                                 capture_output=True, text=True, timeout=20, check=True).stdout
            prs = [p for p in json.loads(out)["data"]["search"]["nodes"]
                   if p and not p["isDraft"] and (p["reviewRequests"]["nodes"] or p["latestReviews"]["nodes"])]
            _sent = (now, prs)
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError, KeyError, TypeError):
            _sent = (now, _sent[1])
    return _sent[1]


def _gh(*args: str) -> str:
    return subprocess.run(["gh", "api", *args], capture_output=True, text=True, timeout=20, check=True).stdout


@functools.lru_cache(maxsize=1)
def login() -> str:
    return _gh("user", "--jq", ".login").strip()


@functools.lru_cache(maxsize=256)
def commit_message(slug: str, sha: str) -> str:
    """Message of one commit. Commits never change, so it is fetched once."""
    return _gh(f"repos/{slug}/commits/{sha}", "--jq", ".commit.message")


def parse_search(items: list) -> list[dict]:
    """search/commits items -> work items. The search only covers default branches, so branch is ''."""
    return [{"slug": it["repository"]["full_name"], "branch": "", "at": it["commit"]["author"]["date"],
             "message": it["commit"]["message"], "url": it["html_url"]} for it in items]


def parse_pushes(events: list) -> list[dict]:
    """PushEvents -> work items, newest push per branch. Events no longer list commits, only the head sha."""
    out: dict[tuple, dict] = {}
    for e in events:
        ref = (e.get("payload") or {}).get("ref") or ""
        if e.get("type") != "PushEvent" or not ref.startswith("refs/heads/"):
            continue
        slug, branch = e["repo"]["name"], ref.removeprefix("refs/heads/")
        if (slug, branch) not in out:  # events come newest first
            out[slug, branch] = {"slug": slug, "branch": branch, "at": e["created_at"], "message": "",
                                 "head": e["payload"].get("head", ""),
                                 "url": f"https://github.com/{slug}/tree/{branch}"}
    return list(out.values())


def my_commits(now: float) -> list[dict]:
    """My commits and pushes of the last MAX_DAYS: {slug, branch, at, message, url, personal}."""
    global _commits
    if now - _commits[0] > REVIEW_TTL_SEC:
        try:
            since = time.strftime("%Y-%m-%d", time.gmtime(now - MAX_DAYS * 86400))
            items = json.loads(_gh("-X", "GET", "search/commits", "-f", f"q=author:@me author-date:>={since}",
                                   "-f", "sort=author-date", "-f", "per_page=100")).get("items", [])
            pushes = parse_pushes(json.loads(_gh(f"users/{login()}/events?per_page=100")))
            for p in pushes[:MAX_BRANCHES]:
                try:
                    p["message"] = commit_message(p["slug"], p["head"]) if p["head"] else ""
                except subprocess.SubprocessError:
                    pass  # a deleted branch or repository; the branch name still says enough
            commits = parse_search(items) + pushes
            for c in commits:
                c["personal"] = c["slug"].split("/")[0].lower() == login().lower()  # my own repos are personal work
            _commits = (now, commits)
        except (subprocess.SubprocessError, OSError, json.JSONDecodeError, KeyError, TypeError):
            _commits = (now, _commits[1])
    return _commits[1]


def review_state(pr: dict) -> str:
    if pr["reviewDecision"] == "APPROVED":
        return "승인됨"
    if pr["reviewDecision"] == "CHANGES_REQUESTED":
        return "수정 요청"
    if pr["latestReviews"]["nodes"]:
        return "코멘트 있음"
    return "리뷰 대기"


@functools.lru_cache(maxsize=64)
def canonical_slug(slug: str) -> str:
    """Current 'owner/name' of a repository, so a renamed repo still matches its old remote URL."""
    out = subprocess.run(["gh", "api", f"repos/{slug}", "--jq", ".full_name"], capture_output=True, text=True, timeout=15)
    return (out.stdout.strip() or slug).lower()


def refresh_forever() -> None:
    while True:
        now = time.time()
        review_requests(now)
        sent_reviews(now)
        my_commits(now)
        time.sleep(REVIEW_TTL_SEC / 2)

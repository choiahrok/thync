"""Build the graph the web page draws (GET /graph.json).

Nodes are sessions, repositories, branches, Jira tickets, PRs, Notion pages and recently edited files. Each node
belongs to a work unit: a Jira epic or ticket, else a branch, else a repository, else the session or Notion page.
Activity sources carry `last_at` (last prompt, commit, ticket update or page edit); model.think() lights the rest.
"""
import time
from pathlib import Path

from . import board, model
from .config import (ACTIVITY_SEC, BACKGROUND_SEC, DEFAULT_DAYS, FILES_PER_SESSION, FILES_SEC, FOCUS_SEC, HANDOFF,
                     JIRA_DONE, JIRA_TODO, LIVE_FILE_SEC, PROFILE_PERSONAL, PROFILE_WORK, PRS_PER_SESSION,
                     RUNNING_STALE_SEC, COMPANY_ROOTS, SESSIONS, SOURCES)
from .reflex import REFLEX_SKILL
from .sources import github, notion
from .sources.claude_code import load_sessions, repo_of
from .sources.jira import BRANCH_KEY, TITLE_KEY, Jira
from .store import load_names, load_reflexes, read_cards
from .util import epoch

SCHEMA = 1
SKIP_BRANCHES = {"main", "master", "HEAD", "develop", ""}


def profile_of(cwd: str) -> str:
    return PROFILE_WORK if any(cwd.startswith(r) for r in COMPANY_ROOTS) else PROFILE_PERSONAL


def build_graph(days: int = DEFAULT_DAYS) -> dict:
    now = time.time()
    window = days * 86400
    sessions = load_sessions(now, window) if SESSIONS else []
    commits = github.my_commits(now) if "github" in SOURCES else []
    pages = notion.recent_pages(now) if "notion" in SOURCES else []
    nodes: dict[str, dict] = {}
    edges: set[tuple[str, str]] = set()
    units: dict[str, dict] = {}
    activity = []
    jira = Jira()
    mine = jira.mine() if "jira" in SOURCES else {}
    reflexes = load_reflexes()

    def node(nid, name, kind, profile, glow=0.0, roles=(), **detail):
        n = nodes.setdefault(nid, {"id": nid, "name": name, "kind": kind, "profile": profile,
                                   "glow": 0.0, "status": "active", "roles": [], "detail": {}})
        n["glow"] = max(n["glow"], glow)
        n["roles"] += [r for r in roles if r not in n["roles"]]
        n["detail"].update(detail)
        return nid

    def edge(a, b):
        if a != b:
            edges.add((min(a, b), max(a, b)))

    def unit(ukey, uname, title, profile, last, keys=(), glow=0.0, working=False, session=False):
        u = units.setdefault(ukey, {"id": ukey, "name": uname, "title": title, "keys": [], "profile": profile,
                                    "updated": 0, "glow": 0.0, "sessions": 0, "working": False})
        if last > u["updated"] and (session or not SESSIONS):  # with session logs, sessions alone order and title units
            u["updated"], u["title"] = int(last), title
        u["glow"] = max(u["glow"], glow)
        u["sessions"] += session
        u["keys"] = sorted(set(u["keys"]) | set(keys))
        u["working"] = u["working"] or working

    def unit_of(keys, repo, branch, own, title):
        """Work unit (id, name): Jira epic/ticket > branch > repository > `own`. Name: epic > ticket > title."""
        if keys:
            ukey, uname = jira.unit_of(keys[0])
            return ukey, title if uname == keys[0] else uname
        if branch:
            return f"branch:{repo}:{branch}", title
        return (f"repo:{repo}", repo) if repo else own

    def touch(nid, at, ukey, **detail):
        """Make a node an activity source, keeping the details of its latest activity. With session logs the
        sessions stay the only sources, so the brain behaves as before; commits, tickets and pages only add nodes."""
        d = nodes[nid]["detail"]
        if at >= d.get("at", 0):
            d.update(at=at, updated=int(at), unit=ukey, **detail)
            if not SESSIONS:
                d.update(last_at=at, act=model.retention(now - at))
        return nid

    def feed(at, kind, text, nid, title, profile):
        if now - at < ACTIVITY_SEC:
            activity.append({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(at)), "kind": kind, "text": text,
                             "session": nid, "title": title, "profile": profile})

    def ticket(key, profile, **extra):
        return node(f"jira:{key}", jira.name(key), "project", profile, kind_label="Jira 티켓", key=key,
                    text=jira.summary(key), jira_status=jira.status(key), url=jira.url(key), **extra)

    # Only treat ABC-123 in a title as a Jira key when the same prefix shows up in a branch name.
    prefixes = {k.split("-")[0].upper() for b in [s.branch for s, _, _ in sessions] + [c["branch"] for c in commits]
                for k in BRANCH_KEY.findall(b)} | {k.split("-")[0] for k in mine}

    # Review requests first, so their PR nodes keep the review role and details.
    for it in (github.review_requests(now) if "github" in SOURCES else []):
        if now - epoch(it["updated_at"]) > window:
            continue
        repo = it["repository_url"].rsplit("/", 1)[-1]
        fresh = now - epoch(it["updated_at"]) < 86400
        pid = node(f"pr:{it['html_url']}", f"{repo} #{it['number']}", "incident", PROFILE_WORK,
                   0.5 if fresh else 0.25, ("review",), kind_label="리뷰 요청", text=it["title"],
                   url=it["html_url"], author=(it.get("user") or {}).get("login", ""), updated=it["updated_at"],
                   repo=repo)
        edge(pid, node(f"repo:{repo}", repo, "repo", PROFILE_WORK, kind_label="저장소", repo=repo))
        for k in TITLE_KEY.findall(it["title"]):
            if k.split("-")[0] in prefixes:
                edge(pid, ticket(k, PROFILE_WORK))

    for s, last, subs in sessions:
        age = now - last
        recent_prompts = [p for p in s.prompts if epoch(p[0]) > now - FOCUS_SEC]
        claude_working = (s.claude_turn and age < RUNNING_STALE_SEC) or subs > 0
        last_prompt_at = epoch(s.prompts[-1][0])
        # A session thync started for a handed-off PR begins with '/<skill> <pr url>'.
        first = s.prompts[0][1].split()
        reflex_url = (first[1] if len(first) > 1 and first[0].lstrip("/") in REFLEX_SKILL.values()
                      and first[1] in reflexes else "")
        # Background: Claude is working and I have not prompted for BACKGROUND_SEC.
        running = bool((claude_working and now - last_prompt_at > BACKGROUND_SEC)
                       or (reflex_url and (claude_working or age < 30 * 60)))
        roles = ("running",) if running else ()
        glow = 0.7 if running else 0.0  # everything else gets its brightness from model.think()
        profile = profile_of(s.cwd)
        repo = repo_of(s.cwd)
        title = s.title or s.ai_title or s.prompts[-1][1][:60]

        branch = "" if s.branch in SKIP_BRANCHES else s.branch
        keys = sorted({k.upper() for k in BRANCH_KEY.findall(branch)} |
                      {k for k in TITLE_KEY.findall(f"{s.title} {s.ai_title}") if k.split("-")[0] in prefixes})
        ukey, uname = unit_of(keys, repo, branch, (f"session:{s.id}", title), title)
        unit(ukey, uname, title, profile, last, keys, glow, running, session=True)

        sid = node(f"session:{s.id}", title, "workThread", profile, glow, roles,
                   kind_label="작업 세션", cwd=s.cwd, branch=s.branch, updated=int(last), working=running,
                   focus_prompts=len(recent_prompts), subagents=subs, claude_working=claude_working,
                   last_at=last_prompt_at, act=model.retention(age), reflex=reflex_url,
                   last_prompt=s.prompts[-1][1][:200], repo=repo, unit=ukey)

        if reflex_url:
            edge(sid, f"pr:{reflex_url}")
        if repo:
            edge(sid, node(f"repo:{repo}", repo, "repo", profile, kind_label="저장소", repo=repo))
        if branch:
            bid = node(f"branch:{repo}:{branch}", branch, "tool", profile, kind_label="브랜치", repo=repo, unit=ukey)
            edge(sid, bid)
            if repo:
                edge(bid, f"repo:{repo}")
        for k in keys:
            edge(sid, ticket(k, profile, repo=repo, unit=ukey))

        prs = sorted(((url, v) for url, v in s.prs.items() if now - epoch(v[0]) <= window),
                     key=lambda kv: kv[1][0])[-PRS_PER_SESSION:]
        for url, (_, prrepo, num) in prs:
            edge(sid, node(f"pr:{url}", f"{prrepo.split('/')[-1]} #{num}", "source", profile,
                           kind_label="PR", url=url, repo=repo, unit=ukey))

        # Files Claude edited in the last hour.
        files = sorted(((fp, ts) for fp, ts in s.files.items() if epoch(ts) > now - FILES_SEC),
                       key=lambda x: x[1])[-FILES_PER_SESSION:]
        for fp, ts in files:
            live = running and epoch(ts) > now - LIVE_FILE_SEC
            edge(sid, node(f"file:{fp}", Path(fp).name, "dailyNote", profile, 0.55 if live else 0.0,
                           ("running",) if live else (), kind_label="파일", path=fp, at=ts, repo=repo, unit=ukey))

        for ts, kind, text in s.events:
            if epoch(ts) > now - ACTIVITY_SEC:
                activity.append({"at": ts, "kind": kind, "text": text, "session": sid, "title": title,
                                 "profile": profile})

    # My commits and pushes. The source is the branch; on a default branch the ticket named in the message, else
    # the repository.
    for c in sorted(commits, key=lambda c: epoch(c["at"])):
        at = epoch(c["at"])
        if now - at > window:
            continue
        owner, repo = c["slug"].split("/", 1)
        profile = PROFILE_PERSONAL if c.get("personal") else PROFILE_WORK
        branch = "" if c["branch"] in SKIP_BRANCHES else c["branch"]
        title = c["message"].strip().split("\n")[0][:100] or branch
        keys = sorted({k.upper() for k in BRANCH_KEY.findall(branch)} |
                      {k for k in TITLE_KEY.findall(c["message"]) if k.split("-")[0] in prefixes})
        ukey, uname = unit_of(keys, repo, branch, None, title)
        unit(ukey, uname, title, profile, at, keys)
        rid = node(f"repo:{repo}", repo, "repo", profile, kind_label="저장소", repo=repo)
        if branch:
            src = node(f"branch:{repo}:{branch}", branch, "tool", profile, kind_label="브랜치", repo=repo)
        else:
            src = ticket(keys[0], profile) if keys else rid
        touch(src, at, ukey, text=title, url=c["url"], branch=c["branch"])
        edge(src, rid)
        for k in keys:
            edge(src, ticket(k, profile, repo=repo, unit=ukey))
        feed(at, "commit", title, src, branch or repo, profile)

    # Tickets assigned to me: in progress, or updated in the last 7 days.
    for key, t in mine.items():
        at = epoch(t.get("updated", ""))
        ukey, uname = jira.unit_of(key)
        unit(ukey, uname, jira.name(key), PROFILE_WORK, at, [key])
        tid = touch(ticket(key, PROFILE_WORK), at, ukey)
        feed(at, "jira", f"{key} {t.get('status', '')}", tid, jira.name(key), PROFILE_WORK)

    # Notion pages edited recently. A Jira key in the title puts the page in that ticket's unit.
    for p in pages:
        at = epoch(p["at"])
        if now - at > window:
            continue
        keys = [k for k in TITLE_KEY.findall(p["title"]) if k.split("-")[0] in prefixes]
        ukey, uname = unit_of(keys, "", "", (f"notion:{p['id']}", p["title"]), p["title"])
        unit(ukey, uname, p["title"], PROFILE_WORK, at, keys)
        pid = touch(node(f"notion:{p['id']}", p["title"], "dailyNote", PROFILE_WORK, kind_label="Notion 페이지",
                         text=p["title"], url=p["url"]), at, ukey)
        for k in keys:
            edge(pid, ticket(k, PROFILE_WORK, unit=ukey))
        feed(at, "notion", p["title"], pid, p["title"], PROFILE_WORK)

    # My PRs waiting on review. A PR a session already linked keeps its unit and gains the role.
    for pr in (github.sent_reviews(now) if "github" in SOURCES else []):
        if now - epoch(pr["updatedAt"]) > window:
            continue
        repo = pr["repository"]["name"]
        state = github.review_state(pr)
        reviewers = [r["requestedReviewer"].get("login") or r["requestedReviewer"].get("name", "")
                     for r in pr["reviewRequests"]["nodes"] if r.get("requestedReviewer")]
        reviewed = [f"{r['author']['login']}:{r['state']}" for r in pr["latestReviews"]["nodes"] if r.get("author")]
        pid = node(f"pr:{pr['url']}", f"{repo} #{pr['number']}", "source", PROFILE_WORK,
                   {"승인됨": 0.55, "수정 요청": 0.6}.get(state, 0.25), ("sent",), kind_label="보낸 리뷰",
                   text=pr["title"], url=pr["url"], review_state=state, reviewers=", ".join(reviewers),
                   reviewed=", ".join(reviewed), updated=pr["updatedAt"], repo=repo)
        edge(pid, node(f"repo:{repo}", repo, "repo", PROFILE_WORK, kind_label="저장소", repo=repo))
        if "unit" not in nodes[pid]["detail"]:
            keys = TITLE_KEY.findall(pr["title"])
            nodes[pid]["detail"]["unit"] = next((jira.unit_of(k)[0] for k in keys if jira.unit_of(k)[0] in units), "sent")

    # Repositories shared by several units go to "common"; review requests join the unit of their ticket.
    for n in nodes.values():
        if n["kind"] == "repo" and "unit" not in n["detail"]:
            n["detail"]["unit"] = n["id"] if n["id"] in units else "common"
        if "review" in n["roles"]:
            keys = TITLE_KEY.findall(n["detail"].get("text", ""))
            n["detail"]["unit"] = next((jira.unit_of(k)[0] for k in keys if jira.unit_of(k)[0] in units), "review")
        n["detail"].setdefault("unit", "common")
    if any(n["detail"]["unit"] == "review" for n in nodes.values()):
        units["review"] = {"id": "review", "name": "리뷰 요청", "title": "나에게 온 리뷰 요청", "profile": PROFILE_WORK,
                           "keys": [], "updated": int(now), "glow": 0.5, "sessions": 0, "working": False}
    if any(n["detail"]["unit"] == "sent" for n in nodes.values()):
        units["sent"] = {"id": "sent", "name": "보낸 리뷰", "title": "내가 올리고 리뷰를 기다리는 PR",
                         "profile": PROFILE_WORK, "keys": [], "updated": int(now), "glow": 0.3, "sessions": 0,
                         "working": False}
    for u in units.values():
        u["count"] = sum(1 for n in nodes.values() if n["detail"]["unit"] == u["id"])

    activity.sort(key=lambda a: a["at"], reverse=True)
    focus_level = model.think(now, nodes, edges)
    # Background: my tickets still in progress that lost the competition for the workspace.
    ws_units = {n["detail"]["unit"] for n in nodes.values() if "focus" in n["roles"]}
    for key, t in (mine.items() if not SESSIONS else ()):
        n = nodes[f"jira:{key}"]
        if t.get("status", "").lower() not in JIRA_TODO | JIRA_DONE and n["detail"]["unit"] not in ws_units:
            n["roles"].append("running")
    model.mark_live(now, nodes, edges)

    # Names changed by hand: node names in names.json, unit names in the card file's title.
    names = load_names()
    for n in nodes.values():
        n["detail"]["auto_name"] = n["name"]
        n["name"] = names.get(n["id"], n["name"])
    card_files = read_cards()
    for u in units.values():
        u["auto_name"] = u["name"]
        u["name"] = card_files.get(u["id"], {}).get("meta", {}).get("title") or names.get(u["id"], u["name"])

    ranked = sorted(units.values(), key=lambda u: (u["working"], u["glow"], u["updated"]), reverse=True)
    return {"schema": SCHEMA, "generated": int(now), "days": days, "focus_level": round(focus_level, 3), "handoff": HANDOFF,
            "units": ranked, "nodes": list(nodes.values()),
            "edges": [list(e) for e in edges if e[0] in nodes and e[1] in nodes], "activity": activity[:40],
            "board": board.build_board(units, nodes, names, card_files)}

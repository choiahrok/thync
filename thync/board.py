"""Kanban cards. One card per work unit; review requests and my PRs under review get one card per PR.

Columns: todo, doing, background, reflex (work handed off to Claude), done. A column set by hand in the
card's Markdown file wins over the automatic one, which stays in `auto_column` so it can be restored.
"""
from .config import HANDOFF, JIRA_DONE, JIRA_TODO, PROFILE_PERSONAL, PROFILE_WORK
from .reflex import tmux_alive
from .store import BOARD_COLUMNS, load_reflexes

REVIEW_STATUS = {"running": "리뷰 중", "posted": "리뷰 올림", "approved": "리뷰 올리고 승인함", "failed": "실패"}


def _auto_column(members: list[dict]) -> str:
    sources = [n for n in members if "last_at" in n["detail"]]
    statuses = {n["detail"].get("jira_status", "").lower() for n in members if n["kind"] == "project"} - {""}
    if any("focus" in n["roles"] for n in sources) or any(n["detail"]["live"] and "running" not in n["roles"]
                                                         for n in sources):
        return "doing"
    if any("running" in n["roles"] for n in sources):
        return "background"
    if any("review" in n["roles"] or "sent" in n["roles"] for n in members):
        return "todo" if any("review" in n["roles"] for n in members) else "doing"
    if statuses - JIRA_TODO - JIRA_DONE:
        return "doing"  # a ticket is still in progress or in review
    if statuses and statuses <= JIRA_TODO:
        return "todo"
    return "done"


def build_board(units: dict, nodes: dict, names: dict, card_files: dict) -> list[dict]:
    by_unit: dict[str, list[dict]] = {}
    for n in nodes.values():
        by_unit.setdefault(n["detail"].get("unit", "common"), []).append(n)

    cards = []
    for uid, u in units.items():
        members = by_unit.get(uid, [])
        if uid in ("review", "sent"):
            for n in members:
                if n["kind"] == "repo":
                    continue
                review = "review" in n["roles"]
                cards.append({"id": n["id"], "title": names.get(n["id"], n["detail"].get("text", n["name"])),
                              "column": "todo" if review else "doing", "profile": n["profile"],
                              "updated": n["detail"].get("updated", ""), "focus": n["id"],
                              "tags": [n["name"], "리뷰 요청" if review else n["detail"].get("review_state", "")]})
            continue
        sessions = [n for n in members if n["kind"] == "workThread"]
        tickets = [n for n in members if n["kind"] == "project"]
        lead = max((n for n in members if "last_at" in n["detail"]), key=lambda n: n["detail"]["last_at"], default=None)
        tags = [t["detail"].get("key", "") for t in tickets][:3]
        tags += [f"세션 {len(sessions)}"] if sessions else []
        reviews = sum("review" in n["roles"] for n in members)
        tags += [f"리뷰 요청 {reviews}"] if reviews else []
        cards.append({"id": uid, "title": u["name"], "sub": u["title"] if u["title"] != u["name"] else "",
                      "column": _auto_column(members), "profile": u["profile"], "updated": u["updated"],
                      "focus": lead["id"] if lead else (members[0]["id"] if members else ""),
                      "tags": [t for t in tags if t]})

    for c in cards:
        c["auto_column"] = c["column"]
        f = card_files.get(c["id"])
        meta = f["meta"] if f else {}
        c["column"] = meta.get("column") if meta.get("column") in BOARD_COLUMNS else c["column"]
        c["title"] = meta.get("title") or c["title"]
        c["note"] = f["note"] if f else ""
        c["moved"] = c["column"] != c["auto_column"]
        c["file"] = str(f["path"]) if f else ""

    # Work handed off to Claude: one card per PR.
    handed = {n["detail"]["reflex"]: n for n in nodes.values() if n["kind"] == "workThread" and n["detail"].get("reflex")}
    for url, r in (load_reflexes() if HANDOFF else {}).items():
        pr = nodes.get(f"pr:{url}")
        session = handed.get(url)
        if "tmux" in r:
            alive = tmux_alive(r["tmux"])
            tags = [r["skill"], "돌고 있음" if alive else "끝남", f"tmux attach -t {r['tmux']}" if alive else ""]
        else:  # a review thync runs itself
            tags = [r.get("skill", ""), "지적 없으면 approve" if r.get("approve") else "",
                    REVIEW_STATUS.get(r.get("status"), ""), r.get("error", "")]
        cards.append({"id": f"reflex:{url}", "title": pr["detail"].get("text", pr["name"]) if pr else url,
                      "sub": pr["name"] if pr else "", "column": "reflex", "auto_column": "reflex", "moved": False,
                      "note": "", "profile": pr["profile"] if pr else PROFILE_WORK, "updated": r["started"],
                      "focus": (session or pr or {}).get("id", ""), "file": "", "tags": [t for t in tags if t]})

    # Card files with no automatic card are cards made by hand.
    auto_ids = {c["id"] for c in cards}
    for cid, f in card_files.items():
        if cid in auto_ids:
            continue
        meta = f["meta"]
        column = meta.get("column") if meta.get("column") in BOARD_COLUMNS else "todo"
        cards.append({"id": cid, "title": meta.get("title") or f["path"].stem, "sub": "", "column": column,
                      "auto_column": column, "moved": False, "note": f["note"],
                      "profile": meta.get("profile", PROFILE_PERSONAL), "updated": int(f["path"].stat().st_mtime),
                      "focus": "", "tags": ["직접 추가"], "file": str(f["path"])})
    return cards

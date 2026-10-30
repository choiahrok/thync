"""Brightness and state rules taken from research on attention and memory (docs/brain-model.md).

Activity sources are nodes with `last_at`: sessions (last prompt), and without session logs also branches and
tickets (last commit), my tickets (last update) and Notion pages (last edit).

1. Memory strength: a source fades after its last activity as a sum of a fast and a slow exponential.
2. Competition: the work unit of the most recent activity pulls from the top down, recency pushes from the
   bottom up, and only the top WORKSPACE_SIZE sources enter the workspace (role "focus").
3. Spreading: a source's activation spreads along edges, halving each hop for SPREAD_HOPS hops, and
   adds up where several sources meet (capped at 1).
4. See-saw: the more focused I am, the dimmer everything outside the workspace; at rest recent work
   glows softly again.
"""
import math

from .config import (FAST_SHARE, FOCUS_SEC, JIRA_DONE, JIRA_TODO, LIVE_SESSION_SEC, SPREAD, SPREAD_HOPS, TAU_FAST,
                     TAU_FOCUS, TAU_SLOW, WORKSPACE_SIZE)


def retention(age: float) -> float:
    """Memory strength 0..1 after `age` seconds."""
    return FAST_SHARE * math.exp(-age / TAU_FAST) + (1 - FAST_SHARE) * math.exp(-age / TAU_SLOW)


def think(now: float, nodes: dict, edges: set) -> float:
    """Set glow, status and the "focus" role on nodes. Returns the focus level 0..1."""
    sources = [n for n in nodes.values() if "last_at" in n["detail"]]
    if not sources:
        return 0.0
    latest = max(sources, key=lambda n: n["detail"]["last_at"])
    focus_level = math.exp(-(now - latest["detail"]["last_at"]) / TAU_FOCUS)
    focus_unit = latest["detail"]["unit"]

    def score(n):
        top_down = 1.0 if n["detail"]["unit"] == focus_unit else 0.0
        bottom_up = retention(now - n["detail"]["last_at"])
        return top_down * focus_level + bottom_up

    candidates = [n for n in sources if "running" not in n["roles"] and not n["detail"].get("reflex")
                  and now - n["detail"]["last_at"] < FOCUS_SEC]
    workspace = sorted(candidates, key=score, reverse=True)[:WORKSPACE_SIZE]
    for n in workspace:
        n["roles"].append("focus")
        n["glow"] = 0.75 + 0.25 * n["detail"]["act"]
    ws_ids = {n["id"] for n in workspace}
    ws_units = {n["detail"]["unit"] for n in workspace}

    adj: dict[str, list[str]] = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    act = {n["id"]: n["detail"]["act"] for n in sources}
    for src in list(act):
        frontier, seen, amount = [src], {src}, act[src]
        for _ in range(SPREAD_HOPS):
            amount *= SPREAD
            nxt = []
            for x in frontier:
                for y in adj.get(x, []):
                    if y in seen or "last_at" in nodes[y]["detail"]:
                        continue
                    seen.add(y)
                    act[y] = min(1.0, act.get(y, 0.0) + amount)
                    nxt.append(y)
            frontier = nxt

    for n in nodes.values():
        a = max(act.get(n["id"], 0.0), n["detail"].get("act", 0.0))
        n["detail"]["act"] = round(a, 3)
        in_ws = n["detail"].get("unit") in ws_units
        if n["id"] not in ws_ids and not {"review", "sent", "running"} & set(n["roles"]):
            # Inside a workspace unit: as bright as its activation. Outside: only while resting (default mode).
            n["glow"] = max(n["glow"], 0.55 * a if in_ws else 0.3 * a * (1 - focus_level))
        status = "active" if a > 0.45 else "dormantRelevant" if a > 0.12 else "archived"
        if focus_level > 0.5 and not in_ws and status == "active":
            status = "dormantRelevant"  # losers of the competition are suppressed
        n["status"] = status
    return focus_level


def mark_live(now: float, nodes: dict, edges: set) -> None:
    """Set detail.live on work that is in progress. The UI puts only live nodes on the brain by default.

    Seeds: focused and background work, sources active within LIVE_SESSION_SEC, open review requests and my
    PRs under review. Nodes directly linked to a seed are live too, except Jira tickets in a to-do or done status.
    """
    def seed(n):
        if {"focus", "running", "review", "sent"} & set(n["roles"]):
            return True
        return "last_at" in n["detail"] and now - n["detail"]["updated"] < LIVE_SESSION_SEC

    def jira_closed(n):
        return n["kind"] == "project" and n["detail"].get("jira_status", "").lower() in JIRA_TODO | JIRA_DONE

    live = {nid for nid, n in nodes.items() if seed(n)}
    for a, b in edges:
        for x, y in ((a, b), (b, a)):
            if x in live and not jira_closed(nodes[y]) and "last_at" not in nodes[y]["detail"]:
                live.add(y)
    for nid, n in nodes.items():
        n["detail"]["live"] = nid in live

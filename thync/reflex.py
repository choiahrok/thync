"""Hand a PR off to Claude.

My PR -> /pr-review-watch in a tmux session, in a local clone of the PR's repository (fix findings, push, reply).
Someone else's PR -> thync.review: thync fetches the PR, Claude only reads it, thync posts the review.
"""
import re
import shlex
import subprocess
import time
from pathlib import Path

from .config import COMPANY_ROOTS, REFLEX_SKILL
from .review import CLAUDE_BIN, start_review
from .sources.claude_code import known_sessions, repo_of
from .sources.github import canonical_slug
from .store import save_reflex

# My own PR: the session must edit, commit and push, so it keeps auto mode; it still may not read secrets.
OWN_PR_PERMISSIONS = ["--permission-mode", "auto", "--disallowedTools", "Read(~/.thync/**)", "Read(~/.ssh/**)",
                      "Read(~/.claude/settings.json)"]

_tmux_cache: dict[str, tuple[float, bool]] = {}


def tmux_alive(name: str) -> bool:
    """Whether a tmux session exists, remembered for 10 s so the 2 s refresh does not spawn tmux each time."""
    seen, alive = _tmux_cache.get(name, (0.0, False))
    if time.time() - seen > 10:
        try:
            alive = subprocess.run(["tmux", "has-session", "-t", f"={name}"], capture_output=True, timeout=5).returncode == 0
        except (subprocess.SubprocessError, OSError):  # no tmux on this machine
            alive = False
        _tmux_cache[name] = (time.time(), alive)
    return alive


def origin_matches(path: str, slug: str) -> bool:
    """Whether `path` is a git clone whose origin is the GitHub repository `owner/name` (renames included)."""
    if not Path(path).is_dir():
        return False
    out = subprocess.run(["git", "-C", path, "remote", "get-url", "origin"], capture_output=True, text=True, timeout=10)
    remote = re.sub(r"^.*github\.com[:/]", "", out.stdout.strip()).removesuffix(".git").lower()
    if out.returncode != 0 or not remote:
        return False
    return remote == slug.lower() or canonical_slug(remote) == canonical_slug(slug)


def find_clone(slug: str, repo: str) -> str | None:
    # Standalone clones under the configured roots first; session folders may be submodules.
    candidates = [str(p) for r in COMPANY_ROOTS for p in sorted(Path(r).glob("*/")) if (p / ".git").is_dir()]
    candidates += [s.cwd.split("/.claude/worktrees/")[0] for s in known_sessions() if s.cwd and repo_of(s.cwd) == repo]
    return next((c for c in dict.fromkeys(candidates) if origin_matches(c, slug)), None)


def start_reflex(node: dict, approve: bool = False) -> tuple[int, str]:
    """Start the session for a PR node. Returns (HTTP status, message for the user)."""
    role = next((r for r in ("sent", "review") if r in node["roles"]), None)
    url, repo = node["detail"].get("url", ""), node["detail"].get("repo", "")
    if not role or not re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+", url):
        return 400, "보낸 리뷰나 리뷰 요청 PR 만 맡길 수 있어요"
    if role == "review":
        return start_review(url, approve)
    slug = "/".join(url.split("/")[3:5])
    root = find_clone(slug, repo)
    if not root:
        return 404, f"이 머신에서 {slug} 저장소 폴더를 찾지 못했어요"
    skill = REFLEX_SKILL[role]
    name = re.sub(r"[^A-Za-z0-9_-]", "-", f"thync-{repo}-{url.rstrip('/').rsplit('/', 1)[-1]}")
    command = shlex.join([CLAUDE_BIN, *OWN_PR_PERMISSIONS, "--", f"/{skill} {url}"])
    # new-session itself refuses a duplicate name, so there is no check-then-create race.
    try:
        out = subprocess.run(["tmux", "new-session", "-d", "-s", name, "-c", root, command],
                             capture_output=True, text=True, timeout=10)
    except (subprocess.SubprocessError, OSError) as e:
        return 500, f"tmux 를 실행하지 못했어요 ({e.__class__.__name__})"
    if out.returncode != 0:
        if "duplicate session" in out.stderr:
            return 409, f"이미 돌고 있어요 (tmux attach -t {name})"
        return 500, f"tmux 를 실행하지 못했어요 ({out.stderr.strip()[:200]})"
    _tmux_cache.pop(name, None)
    save_reflex(url, {"tmux": name, "skill": skill, "cwd": root, "started": int(time.time())})
    return 202, f"{skill} 를 시작했어요 (tmux attach -t {name})"

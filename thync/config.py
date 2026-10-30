"""Paths, user settings and tuning constants.

Everything personal (company folders, Jira URL, tokens, collected data) lives outside the
repository in THYNC_HOME (default ~/.thync). See config.example.json.
"""
import json
import os
import shutil
from pathlib import Path

HOME = Path.home()
STATE_DIR = Path(os.environ.get("THYNC_HOME", HOME / ".thync")).expanduser()
CONFIG_FILE = STATE_DIR / "config.json"
CLAUDE_LOGS = HOME / ".claude" / "projects"
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


CONFIG = _load_config()
# Sessions started under these folders belong to the work profile; the rest are personal.
# The same folders are searched for local clones when work is handed off to Claude.
COMPANY_ROOTS = [str(Path(p).expanduser()) for p in CONFIG.get("company_roots", [])]
JIRA_BROWSE = CONFIG.get("jira_browse_url", "")  # e.g. https://example.atlassian.net/browse/
JIRA_EMAIL = CONFIG.get("jira_email", "")  # with an API token, turns on fetching ticket summaries
CARDS_DIR = Path(CONFIG.get("cards_dir", STATE_DIR / "cards")).expanduser()
# Claude Code skills started when a PR is handed off: my PR -> "sent", someone else's PR -> "review".
REFLEX_SKILL = {"sent": "pr-review-watch", **CONFIG.get("reflex_skills", {})}
# Where work comes from: "claude_code" (session logs), "github" (reviews, my PRs, my commits), "jira", "notion".
SOURCES = set(CONFIG.get("sources", ["claude_code", "github", "jira", "notion"]))
SESSIONS = "claude_code" in SOURCES
NOTION_USER = CONFIG.get("notion_user_id", "")  # only pages last edited by this Notion user; empty = every page
# Handing PRs off to Claude needs the claude CLI and the session logs it writes.
HANDOFF = SESSIONS and shutil.which("claude") is not None
HOST = "127.0.0.1"
PORT = int(CONFIG.get("port", 8765))

PROFILE_WORK, PROFILE_PERSONAL = "회사", "개인"

# --- Time windows (seconds) ---
# Commits, ticket changes and page edits come hours apart, not minutes like prompts, so without session
# logs the focus window, its cooling and the feed widen (docs/brain-model.md).
FOCUS_SEC = 60 * 60 if SESSIONS else 8 * 3600  # activity within this window counts toward focus
BACKGROUND_SEC = 10 * 60         # Claude working but no prompt from me for this long -> background
RUNNING_STALE_SEC = 5 * 60       # Claude's turn but the log has been quiet this long -> treat as stopped
LIVE_FILE_SEC = 10 * 60          # files edited this recently glow
FILES_SEC = 60 * 60              # files edited this recently become nodes
LIVE_SESSION_SEC = 24 * 3600     # sessions talked to this recently are "in progress"
ACTIVITY_SEC = 30 * 60 if SESSIONS else 24 * 3600  # live activity feed window
REVIEW_TTL_SEC = 120             # how long GitHub results are reused
DEFAULT_DAYS, MAX_DAYS = 7, 30   # period selector

# --- Brain model (sources in docs/brain-model.md). Only WORKSPACE_SIZE comes from a paper. ---
WORKSPACE_SIZE = 4                                     # Cowan 2001: about 4 items (3-5)
TAU_FAST, TAU_SLOW, FAST_SHARE = 3600, 5 * 86400, 0.7  # two-exponential forgetting (Murre & Dros 2015)
SPREAD, SPREAD_HOPS = 0.5, 2                           # spreading activation (Collins & Loftus 1975)
TAU_FOCUS = 10 * 60 if SESSIONS else 2 * 3600         # how fast focus cools after the last activity

# --- Graph size limits ---
PRS_PER_SESSION = 3
FILES_PER_SESSION = 8

# Jira statuses (lowercased) that never go on the brain, even when linked to live work.
JIRA_TODO = {"backlog", "해야 할 일", "to do"}
JIRA_DONE = {"완료", "done", "종료", "closed", "resolved"}

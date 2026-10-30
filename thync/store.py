"""Files thync writes under STATE_DIR: access token, renamed nodes, kanban cards, handed-off sessions.

Kanban cards are one Markdown file per card: id, column and title in the front matter, the note in the
body. Any editor (or Obsidian) can change them, and a new file becomes a hand-made card.
"""
import hashlib
import os
import re
import secrets
import threading
from pathlib import Path

from .config import CARDS_DIR, STATE_DIR
from .util import read_json, write_json

TOKEN_FILE = STATE_DIR / "token"
NAMES_FILE = STATE_DIR / "names.json"
REFLEX_FILE = STATE_DIR / "reflex.json"

BOARD_COLUMNS = {"todo", "doing", "background", "done"}
WRITE_LOCK = threading.Lock()  # read-modify-write of these files happens on request threads
CARD_KEYS = ("id", "title", "column", "profile", "manual")


# --- Access token ---

def load_token() -> str:
    """Return the token in STATE_DIR/token, creating it (readable only by me) on first run."""
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)
    if not TOKEN_FILE.exists() or not TOKEN_FILE.read_text(encoding="utf-8").strip():  # an empty token would let anyone in
        TOKEN_FILE.write_text(secrets.token_urlsafe(24), encoding="utf-8")
    os.chmod(TOKEN_FILE, 0o600)
    return TOKEN_FILE.read_text(encoding="utf-8").strip()


# --- Names changed in the UI (node id -> name) ---

def load_names() -> dict:
    return read_json(NAMES_FILE, {})


def save_name(nid: str, name: str) -> None:
    with WRITE_LOCK:
        _save_name(nid, name)


def _save_name(nid: str, name: str) -> None:
    names = load_names()
    if name:
        names[nid] = name
    else:
        names.pop(nid, None)  # empty name = back to the automatic name
    write_json(NAMES_FILE, names)


# --- Sessions handed off to Claude (PR url -> record) ---

def load_reflexes() -> dict:
    return read_json(REFLEX_FILE, {})


def save_reflex(url: str, record: dict) -> None:
    with WRITE_LOCK:
        reflexes = load_reflexes()
        reflexes[url] = record
        write_json(REFLEX_FILE, reflexes)


# --- Kanban cards as Markdown files ---

def parse_card(text: str) -> tuple[dict, str]:
    """'---\\nkey: value\\n---\\nbody' -> (meta, body). Values are single-line strings."""
    meta: dict[str, str] = {}
    if text.startswith("---\n") and "\n---" in text[4:]:
        head, body = text[4:].split("\n---", 1)
        for line in head.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip('"')
        return meta, body.lstrip("\n")
    return meta, text


def read_cards() -> dict[str, dict]:
    cards = {}
    for path in sorted(CARDS_DIR.glob("*.md")):
        try:
            meta, note = parse_card(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        cid = meta.get("id") or f"manual:{path.stem}"
        cards[cid] = {"path": path, "meta": meta, "note": note.strip()}
    return cards


def card_path(cid: str) -> Path:
    # The hash keeps ids that differ only after the cut, or only in punctuation, in separate files.
    slug = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", cid).strip("_")[:60] or "card"
    return CARDS_DIR / f"{slug}-{hashlib.sha1(cid.encode()).hexdigest()[:8]}.md"


def save_card(cid: str, change: dict) -> None:
    """Apply a change (column, title, note, reset, ...) to a card file. A card with nothing left is deleted."""
    with WRITE_LOCK:
        _save_card(cid, change)


def _save_card(cid: str, change: dict) -> None:
    cards = read_cards()
    card = cards.get(cid, {"path": card_path(cid), "meta": {"id": cid}, "note": ""})
    meta, note = dict(card["meta"]), card["note"]
    meta["id"] = cid
    if change.get("reset"):
        meta.pop("column", None)  # back to the automatic column
    for key in ("column", "title", "profile", "manual"):
        if change.get(key):
            meta[key] = change[key]
    if "title" in change and not change["title"]:
        meta.pop("title", None)
    if "note" in change:
        note = change["note"]
    path = card["path"]
    if not note and set(meta) <= {"id"}:
        path.unlink(missing_ok=True)
        return
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    head = "\n".join(f"{k}: {' '.join(str(meta[k]).split())}" for k in CARD_KEYS if meta.get(k))
    tmp = path.with_suffix(".tmp")
    tmp.write_text(f"---\n{head}\n---\n\n{note.strip()}\n", encoding="utf-8")
    tmp.replace(path)

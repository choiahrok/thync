"""Small helpers shared by several modules."""
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path


def epoch(ts: str) -> float:
    """ISO-8601 UTC timestamp ('2026-10-22T10:04:48.123Z') -> seconds since the epoch. 0.0 if unparsable."""
    try:
        # Python 3.10 needs the offset as +09:00; Jira writes +0900.
        return datetime.fromisoformat(re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", ts.replace("Z", "+00:00"))).timestamp()
    except (ValueError, AttributeError):
        return 0.0


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_text(path: Path, text: str) -> None:
    """Write atomically so a reader never sees half a file. The temp file is created fresh (O_EXCL), so in a
    shared folder such as an Obsidian vault nobody can plant a symlink at a predictable temp name."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_json(path: Path, data) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=1))


def read_secret(path: Path) -> str:
    """A token file's contents; warns once when other users can read it."""
    if not path.is_file():
        return ""
    if path.stat().st_mode & 0o077 and path not in _warned:
        _warned.add(path)
        print(f"thync: {path} can be read by other users; run chmod 600 {path}", file=sys.stderr, flush=True)
    return path.read_text().strip()


_warned: set[Path] = set()

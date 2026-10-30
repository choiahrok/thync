"""Small helpers shared by several modules."""
import json
import re
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


def write_json(path: Path, data) -> None:
    """Write atomically so a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)

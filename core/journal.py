"""The journal: every event (proposal, decision, fill, exit, block) appended to one JSON-lines file a day.

Append-only, so nothing is ever overwritten. Each event has an event_id; if the same event is written
again (a re-sent report, a retried export), readers keep only the newest copy, so it is counted once.

Writes go to a local file first (fast, locked); with a mirror (the state bucket) the whole day file is
copied there after each event, and restore() brings it back on a fresh GitHub runner.
"""
import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

_lock = threading.Lock()  # the session writes from several threads (lesson of 25 Nov: unlocked appends mixed lines)


def _rel(day, name):
    """One file per writer and day (intraday: <day>.jsonl, a pool: <day>-<pool>.jsonl), so jobs on different
    runners never overwrite each other's copy in the state bucket."""
    return f"journal/{day}.jsonl" if name is None else f"journal/{day}-{name}.jsonl"


def _path(day, base_dir, name=None):
    return Path(base_dir or os.environ.get("UPX_DATA_DIR", "data")) / _rel(day, name)


def append(day, event, *, base_dir=None, mirror=None, name=None, event_id=None, **fields):
    """Write one event for `day` (YYYY-MM-DD) and return its event_id."""
    row = {"event": event, "event_id": event_id or uuid.uuid4().hex,
           "written_at": datetime.now().isoformat(timespec="seconds"), **fields}
    path = _path(day, base_dir, name)
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
        if mirror is not None:
            mirror.put(_rel(day, name), path.read_bytes())
    return row["event_id"]


def restore(day, *, base_dir=None, mirror, name=None):
    """Copy the day's journal from the mirror to the local file, if the local one is missing."""
    path = _path(day, base_dir, name)
    body = mirror.get(_rel(day, name))
    if body is not None and not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)


def read(day, *, base_dir=None, name=None):
    """The day's events in order, each event_id once (the newest copy)."""
    path = _path(day, base_dir, name)
    if not path.exists():
        return []
    latest = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:  # a line cut short by a crash; every complete event is still read
            continue
        latest.pop(row["event_id"], None)  # re-insert so the newest copy keeps its place at the end
        latest[row["event_id"]] = row
    return list(latest.values())

"""Save a trading session's step-by-step record (every tool call and the AI's reasoning) to the bucket, and print
the AI's final summary into the Actions log. The record is not kept as a GitHub artifact because the repo is public.

Usage: python scripts/save_transcript.py <record.jsonl> <phase>
"""
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import storage  # noqa: E402


def save(path, phase, day, store=None):
    """Upload the record to transcripts/<day>-<phase>.jsonl and return the summary, tool counts and minutes."""
    path = Path(path)
    if not path.exists():
        return {"summary": f"no session record at {path}", "tools": {}, "minutes": None}
    body = path.read_bytes()
    (store or storage.backend()).put(f"transcripts/{day.isoformat()}-{phase}.jsonl", body)
    tools, summary, minutes = Counter(), "", None
    for line in body.decode("utf-8", "replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue  # a stray non-JSON line must not lose the rest of the record
        if row.get("type") == "assistant":
            for part in (row.get("message") or {}).get("content") or []:
                if part.get("type") == "tool_use":
                    tools[part["name"].removeprefix("mcp__trader__")] += 1
        elif row.get("type") == "result":
            summary = row.get("result") or ""
            minutes = round((row.get("duration_ms") or 0) / 60000, 1)
    return {"summary": summary, "tools": dict(tools), "minutes": minutes}


if __name__ == "__main__":
    day = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
    out = save(sys.argv[1], sys.argv[2], day)
    print(out["summary"])
    print(f"\ntool calls: {out['tools']}  ·  minutes: {out['minutes']}")

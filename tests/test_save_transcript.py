"""scripts/save_transcript.py: the session's step-by-step record into the bucket, and its final summary."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from core import storage
from scripts import save_transcript as st


class SaveTest(unittest.TestCase):
    def test_saves_the_record_and_returns_the_summary(self):
        lines = [{"type": "system", "subtype": "init"},
                 {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "mcp__trader__get_facts"}]}},
                 {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "mcp__trader__get_facts"},
                                                               {"type": "text", "text": "thinking"}]}},
                 {"type": "result", "result": "No trades today.", "duration_ms": 61000, "num_turns": 7}]
        path = Path(tempfile.mkdtemp()) / "t.jsonl"
        path.write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
        store = storage.Local(tempfile.mkdtemp())
        out = st.save(path, "morning", date(2026, 12, 14), store=store)
        self.assertEqual(out["summary"], "No trades today.")
        self.assertEqual(out["tools"], {"get_facts": 2})
        self.assertEqual(out["minutes"], 1.0)
        self.assertEqual(store.get("transcripts/2026-12-14-morning.jsonl"), path.read_bytes())

    def test_a_missing_record_is_reported_not_raised(self):
        out = st.save(Path("/nonexistent.jsonl"), "morning", date(2026, 12, 14), store=storage.Local(tempfile.mkdtemp()))
        self.assertIn("no session record", out["summary"])


if __name__ == "__main__":
    unittest.main()

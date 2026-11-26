"""scripts/check_isolation.py finds references to the old repos' resources."""  # isolation-ok
import tempfile
import unittest
from pathlib import Path

from scripts import check_isolation


class IsolationTest(unittest.TestCase):
    def repo(self, files):
        root = Path(tempfile.mkdtemp())
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text)
        return root

    def test_flags_old_bucket_and_parameter(self):
        root = self.repo({
            "core/a.py": 'B = "stocks-trader-state-123"\n',  # isolation-ok
            "infra/b.tf": 'name = "/stocks/telegram-bot-token"\n',  # isolation-ok
        })
        self.assertEqual(sorted(f for f, _, _ in check_isolation.find(root)), ["core/a.py", "infra/b.tf"])

    def test_ignores_docs_and_marked_lines(self):
        root = self.repo({
            "docs/PLAN.md": "old prefix stocks-\n",  # isolation-ok
            "jobs/copy.py": 'SRC = "stocks-landing"  # isolation-ok\n',  # isolation-ok
            "core/c.py": 'NAME = "upx-state"\n',
        })
        self.assertEqual(check_isolation.find(root), [])


if __name__ == "__main__":
    unittest.main()

"""Fail if code or infra refers to a resource owned by the old repos.  # isolation-ok

Removing the old stacks must not break this repo, so nothing outside docs/ may name an old bucket,
Lambda, role or SSM parameter. A line that must (the one-time copy job) ends with "# isolation-ok".
Usage: python scripts/check_isolation.py
"""
import re
import sys
from pathlib import Path

OLD = re.compile(r"stocks-|/stocks/")  # isolation-ok
SKIP_DIRS = {".git", "docs", "__pycache__", ".terraform"}
MARK = "isolation-ok"


def find(root):
    """Return [(relative path, line number, line)] for every unmarked reference."""
    root = Path(root)
    hits = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if not path.is_file() or SKIP_DIRS & set(rel.parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue  # images and other binary files
        hits += [(rel.as_posix(), n, line.strip()) for n, line in enumerate(lines, 1)
                 if OLD.search(line) and MARK not in line]
    return hits


if __name__ == "__main__":
    found = find(Path(__file__).resolve().parent.parent)
    for rel, n, line in found:
        print(f"{rel}:{n}: {line}")
    sys.exit(1 if found else 0)

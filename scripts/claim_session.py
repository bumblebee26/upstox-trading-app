"""Claim today's session phase once, so the manual start, the kicker and the cron backup can't run it twice.

Usage: python scripts/claim_session.py morning|afternoon   (exit code 1 if it was already claimed today)
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import storage  # noqa: E402

if __name__ == "__main__":
    phase = sys.argv[1]
    if phase not in ("morning", "afternoon"):
        sys.exit("phase must be morning or afternoon")
    day = datetime.now(timezone(timedelta(hours=5, minutes=30))).date().isoformat()
    if storage.backend().claim(f"claims/{day}-{phase}"):
        print(f"claimed {day} {phase}")
    else:
        print(f"{day} {phase} already ran today; not starting again")
        sys.exit(1)

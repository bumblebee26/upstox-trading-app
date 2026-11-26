"""One-time copy of the old system's market history into this repo's own volume (dummy-money paper trader).

Files only, never tables: the old landing volume's NSE, US and macro history goes to
/Volumes/upx/bronze/history/<source>/, keeping each file's path, so the old catalog can be deleted later
without touching anything here. Old news is copied only if it covers more than a week. Each source is
checked by file count and bytes after the copy, and a short inventory (dates, file types, a sample) is
printed so the loading tables can be written to match the real files.

Runs in Databricks as the job upx-history-copy (started by .github/workflows/history.yml). Safe to run again:
files already copied with the same size are skipped. Delete this file after the copy is checked.
"""
import json
import re
import sys

OLD_ROOT = "/Volumes/stocks/bronze"  # isolation-ok (the one-time copy)
NEW_ROOT = "/Volumes/upx/bronze/history"
SOURCES = ["nse", "nse_delivery", "nse_indices", "nse_fo", "fundamentals", "index_members", "massive", "fred"]
NEWS_MIN_DAYS = 7
DAY = re.compile(r"date=(\d{4}-\d{2}-\d{2})")


def walk(fs, path):
    """{path: size} of every file under path ({} if the folder doesn't exist)."""
    try:
        entries = fs.ls(path)
    except Exception:  # noqa: BLE001 - a missing folder reads as empty
        return {}
    out = {}
    for e in entries:
        if e.name.endswith("/"):
            out.update(walk(fs, e.path))
        else:
            out[e.path] = e.size
    return out


def copy_tree(fs, src, dst):
    """Copy what is missing (or a different size); then compare counts and bytes."""
    old = walk(fs, src)
    if not old:
        return None
    new = walk(fs, dst)
    copied = 0
    for path, size in sorted(old.items()):
        target = dst + path[len(src):]
        if new.get(target) != size:
            fs.cp(path, target)
            copied += 1
    after = walk(fs, dst)
    mirrored = {p: s for p, s in after.items() if (src + p[len(dst):]) in old}
    days = sorted({m.group(1) for p in old if (m := DAY.search(p))})
    types = {}
    for p in old:
        ext = p.rsplit(".", 1)[-1].lower() if "." in p.rsplit("/", 1)[-1] else "none"
        types[ext] = types.get(ext, 0) + 1
    sample_path = sorted(old)[-1]
    try:
        sample = fs.head(sample_path, 400)
    except Exception:  # noqa: BLE001 - a binary or zipped file has no readable sample
        sample = "(not readable as text)"
    return {"files": len(old), "bytes": sum(old.values()), "copied": copied,
            "verified": len(mirrored) == len(old) and sum(mirrored.values()) == sum(old.values()),
            "first_day": days[0] if days else None, "last_day": days[-1] if days else None,
            "types": types, "sample_file": sample_path[len(src):], "sample": sample}


def run(fs, sources=SOURCES, news_min_days=NEWS_MIN_DAYS):
    report = {}
    for source in sources:
        r = copy_tree(fs, f"{OLD_ROOT}/landing/{source}", f"{NEW_ROOT}/{source}")
        report[source] = r if r is not None else {"skipped": "not in the old volume"}
    news_days = {m.group(1) for p in walk(fs, f"{OLD_ROOT}/news") if (m := DAY.search(p))}
    if len(news_days) > news_min_days:
        report["news"] = copy_tree(fs, f"{OLD_ROOT}/news", f"{NEW_ROOT}/news")
    else:
        report["news"] = {"skipped": f"only {len(news_days)} days of news (the owner asked for more than a week)"}
    return report


if __name__ == "__main__":
    from databricks.sdk.runtime import dbutils  # only inside Databricks

    result = run(dbutils.fs)
    for name, r in result.items():
        print(json.dumps({"source": name, **r}, ensure_ascii=False))
    if any(r.get("verified") is False for r in result.values()):
        sys.exit("a copy did not verify (count or bytes differ); run the job again")

"""Copy the state bucket into the Databricks landing volume as JSON lines, then start the lakehouse pipeline
(dummy-money paper trader). Free Edition can't read the bucket, so files are pushed in, 4 times a day.

Landing layout (/Volumes/upx/bronze/landing/<source>/...), one JSON object per line:
  journal/<day>[-<pool>].jsonl   the journals as they are (rewritten whole as the day goes on)
  feed/<day>.jsonl               every Telegram message the system sent
  shadow_trades/<day>.jsonl      intraday shadow trades, one per line with its variant
  shadow_status/<day>.jsonl      each shadow's family, luck line and status that day
  shadow_ledgers/<day>.jsonl     each swing, long-term and benchmark ledger's value that day
  pools/<day>-<pool>.jsonl       the real pools' balance as last saved
  nse_bhav/, nse_deals/, nse_filings/, nse_calendar/   the NSE files of the day
Only files whose content changed since the last upload are sent (lakehouse/manifest.json in the bucket).

Three pipelines, each run only at its own times and only if its folders got new files (Free Edition: one
pipeline at a time, a daily compute quota). The AWS kicker names the pipeline for each start:
  upx-trading   journal, pools, feed                         13:05 and 16:55 IST
  upx-shadows   shadow_trades, shadow_status, shadow_ledgers  17:30 IST
  upx-market    nse_* (and the copied history)               20:05 IST

  UPX_PIPELINES=trading python -m lakehouse.sync
"""
import hashlib
import json
import logging
import os
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

from core import http, storage

log = logging.getLogger("upx")
IST = timezone(timedelta(hours=5, minutes=30))
VOLUME = "/Volumes/upx/bronze/landing"
MANIFEST = "lakehouse/manifest.json"
FOLDERS = {"trading": ("journal", "pools", "feed"),
           "shadows": ("shadow_trades", "shadow_status", "shadow_ledgers"),
           "market": ("nse_bhav", "nse_deals", "nse_filings", "nse_calendar")}
POOLS = ("intraday", "swing", "long_term")


def _jsonl(rows):
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows).encode()


def landing_files(store, today, back_days=3):
    """{landing path: JSON-lines body} for today and the `back_days` days before."""
    out = {}
    for back in range(back_days + 1):
        day = (today - timedelta(days=back)).isoformat()
        for key in store.list(f"journal/{day}"):
            out[key] = store.get(key)
        feed = [storage.get_json(k, store=store) for k in store.list(f"feed/{day}/")]
        if feed:
            out[f"feed/{day}.jsonl"] = _jsonl(feed)
        intraday = storage.get_json(f"shadows/intraday/{day}.json", store=store)
        if intraday:
            out[f"shadow_trades/{day}.jsonl"] = _jsonl(
                dict({"day": day, "variant": name}, **t)
                for name, v in sorted(intraday["variants"].items()) for t in v.get("trades") or [])
        bhav = storage.get_json(f"nse/{day}/bhav.json", store=store)
        if bhav:
            out[f"nse_bhav/{day}.jsonl"] = _jsonl(dict({"day": day, "symbol": s}, **r) for s, r in sorted(bhav.items()))
        for kind in ("bulk", "block"):
            deals = storage.get_json(f"nse/{day}/{kind}.json", store=store)
            if deals:
                out[f"nse_deals/{day}-{kind}.jsonl"] = _jsonl(dict(r, kind=kind, saved_on=day) for r in deals)
        for name in ("filings", "calendar"):
            rows = storage.get_json(f"nse/{day}/{name}.json", store=store)
            if rows:
                out[f"nse_{name}/{day}.jsonl"] = _jsonl(dict(r, saved_on=day) for r in rows)
    # Snapshots: only the latest copy exists, so it is filed under the day it describes.
    fam = storage.get_json("shadows/families.json", store=store)
    if fam and fam.get("day"):
        out[f"shadow_status/{fam['day']}.jsonl"] = _jsonl(dict({"day": fam["day"]}, **r) for r in fam["rows"])
    book = storage.get_json("shadows/ledgers.json", store=store)
    if book and book.get("day"):
        out[f"shadow_ledgers/{book['day']}.jsonl"] = _jsonl(
            {"day": book["day"], "id": i, "capital": led["capital"], "cash": led["cash"],
             "value": led["equity"][-1][1] if led.get("equity") else led["capital"],
             "holdings": len(led.get("holdings") or {}), "closed": len(led.get("closed") or [])}
            for i, led in sorted(book["ledgers"].items()))
    for pool in POOLS:
        st = storage.get_json(f"state/{pool}.json", store=store)
        if st and st.get("day"):
            out[f"pools/{st['day']}-{pool}.jsonl"] = _jsonl([
                {"day": st["day"], "pool": pool, "balance": st.get("balance"),
                 "starting_capital": st.get("starting_capital"), "realized_today": st.get("realized_today"),
                 "open_positions": len(st.get("positions") or {})}])
    return {k: v for k, v in out.items() if v}


def _auth():
    return {"Authorization": f"Bearer {os.environ['DATABRICKS_TOKEN']}"}


def _host():
    return os.environ["DATABRICKS_HOST"].rstrip("/")


def upload(path, body):
    """Databricks Files API: write one file in a volume (overwriting)."""
    url = f"{_host()}/api/2.0/fs/files{urllib.parse.quote(path)}?overwrite=true"
    http.request("PUT", url, data=body, headers=dict(_auth(), **{"Content-Type": "application/octet-stream"}),
                 log_url=f"databricks files {path}")


def pipeline_of(path):
    folder = path.split("/", 1)[0]
    return next(p for p, folders in FOLDERS.items() if folder in folders)


def mark_pending(pending, sent):
    """Note which pipelines have new files waiting."""
    for path in sent:
        pending[pipeline_of(path)] = True
    return pending


def due(pending, wanted, force=False):
    """The pipelines this start should run: the ones it names that have new files (or all, when forced)."""
    return [p for p in wanted if force or pending.get(p)]


def start_pipeline(short):
    name = f"upx-{short}"
    query = urllib.parse.urlencode({"filter": f"name LIKE '{name}'"})
    found = json.loads(http.request("GET", f"{_host()}/api/2.0/pipelines?{query}", headers=_auth(),
                                    log_url="databricks list pipelines"))
    ids = [p["pipeline_id"] for p in found.get("statuses", []) if p.get("name") == name]
    if not ids:
        raise RuntimeError(f"pipeline {name} not found; apply infra/databricks first")
    started = json.loads(http.request("POST", f"{_host()}/api/2.0/pipelines/{ids[0]}/updates", data=b"{}",
                                      headers=dict(_auth(), **{"Content-Type": "application/json"}),
                                      log_url="databricks start update"))
    return ids[0], started.get("update_id")


def wait(pipeline_id, update_id, sleep=time.sleep, every=20, limit=60):
    """Poll the update until it ends (at most limit x every seconds); return its state and error messages."""
    state = None
    for _ in range(limit):
        reply = json.loads(http.request("GET", f"{_host()}/api/2.0/pipelines/{pipeline_id}/updates/{update_id}",
                                        headers=_auth(), log_url="databricks update state"))
        state = (reply.get("update") or {}).get("state")
        if state in ("COMPLETED", "FAILED", "CANCELED"):
            break
        sleep(every)
    errors = []
    if state != "COMPLETED":
        query = urllib.parse.urlencode({"filter": "level='ERROR'", "max_results": 10})
        events = json.loads(http.request("GET", f"{_host()}/api/2.0/pipelines/{pipeline_id}/events?{query}",
                                         headers=_auth(), log_url="databricks events"))
        for e in events.get("events", []):
            detail = "; ".join(x.get("message", "") for x in (e.get("error") or {}).get("exceptions", []))
            errors.append(f"{e.get('message', '')}: {detail}"[:1000])
    return state, errors


def run(today, store=None, put=upload, back_days=3):
    """Upload what changed. The manifest is saved even when an upload fails, so the next run carries on."""
    store = store or storage.backend()
    seen = storage.get_json(MANIFEST, {}, store=store)
    sent = []
    try:
        for path, body in sorted(landing_files(store, today, back_days).items()):
            digest = hashlib.sha256(body).hexdigest()
            if seen.get(path) != digest:
                put(f"{VOLUME}/{path}", body)
                seen[path] = digest
                sent.append(path)
    finally:
        seen["_pending"] = mark_pending(seen.get("_pending", {}), sent)
        storage.put_json(MANIFEST, seen, store=store)
    return sent


def ran(store, short):
    """A pipeline's run finished: its waiting files are loaded."""
    seen = storage.get_json(MANIFEST, {}, store=store)
    seen.setdefault("_pending", {})[short] = False
    storage.put_json(MANIFEST, seen, store=store)


if __name__ == "__main__":
    store = storage.backend()
    files = run(datetime.now(IST).date(), store=store)
    wanted = [p for p in os.environ.get("UPX_PIPELINES", "").split() if p in FOLDERS]
    todo = due(storage.get_json(MANIFEST, {}, store=store).get("_pending", {}), wanted,
               force=os.environ.get("UPX_FORCE_PIPELINE") == "true")
    print(json.dumps({"uploaded": len(files), "asked": wanted, "running": todo}))
    for short in todo:  # one after another: Free Edition runs one pipeline at a time
        pid, uid = start_pipeline(short)
        state, errors = wait(pid, uid)
        print(json.dumps({"pipeline": f"upx-{short}", "update": uid, "state": state}))
        for err in errors:
            print("ERROR", err)
        if state != "COMPLETED":
            raise SystemExit(f"upx-{short} update {uid} ended {state}")
        ran(store, short)

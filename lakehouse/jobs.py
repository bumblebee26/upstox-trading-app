"""Start a Databricks job by name from GitHub, wait for it, and print what it printed.

  python -m lakehouse.jobs upx-history-copy
"""
import json
import sys
import time
import urllib.parse

from core import http
from lakehouse.sync import _auth, _host


def _call(method, path, body=None):
    headers = dict(_auth(), **({"Content-Type": "application/json"} if body is not None else {}))
    return json.loads(http.request(method, f"{_host()}{path}", headers=headers,
                                   data=json.dumps(body).encode() if body is not None else None,
                                   log_url=f"databricks {path.split('?')[0]}"))


def run(name, sleep=time.sleep, every=20, limit=180):
    """Run job `name` once; return (result state, the task's printed output)."""
    found = _call("GET", "/api/2.1/jobs/list?" + urllib.parse.urlencode({"name": name}))
    ids = [j["job_id"] for j in found.get("jobs", []) if j["settings"]["name"] == name]
    if not ids:
        raise RuntimeError(f"job {name} not found; apply infra/databricks first")
    run_id = _call("POST", "/api/2.1/jobs/run-now", {"job_id": ids[0]})["run_id"]
    for _ in range(limit):
        info = _call("GET", f"/api/2.1/jobs/runs/get?run_id={run_id}")
        if info["state"]["life_cycle_state"] in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR"):
            break
        sleep(every)
    result = info["state"].get("result_state") or info["state"]["life_cycle_state"]
    logs = []
    for task in info.get("tasks", []):
        out = _call("GET", f"/api/2.1/jobs/runs/get-output?run_id={task['run_id']}")
        logs.append(out.get("logs") or out.get("error") or "")
    return result, "\n".join(logs)


if __name__ == "__main__":
    result, logs = run(sys.argv[1])
    print(logs)
    print("result:", result)
    if result != "SUCCESS":
        sys.exit(1)

"""Run SQL on the Databricks SQL warehouse (Statement Execution API), with the Lakehouse job's host and token.

Free Edition comes with one serverless warehouse; we use the first one the workspace lists unless
DATABRICKS_WAREHOUSE_ID names another.
"""

import json
import os
import time

from core import http

NUMBERS = {"BYTE", "SHORT", "INT", "LONG", "FLOAT", "DOUBLE", "DECIMAL"}
INTEGERS = {"BYTE", "SHORT", "INT", "LONG"}
_warehouse = None


def _call(method, path, body=None):
    host = os.environ["DATABRICKS_HOST"].rstrip("/")
    headers = {"Authorization": f"Bearer {os.environ['DATABRICKS_TOKEN']}", "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    return json.loads(http.request(method, f"{host}{path}", headers=headers, data=data, timeout=60))


def warehouse_id():
    global _warehouse
    if _warehouse is None:
        _warehouse = os.environ.get("DATABRICKS_WAREHOUSE_ID") or _call("GET", "/api/2.0/sql/warehouses")["warehouses"][0]["id"]
    return _warehouse


def to_rows(reply):
    cols = reply["manifest"]["schema"]["columns"]
    out = []
    for raw in (reply.get("result") or {}).get("data_array") or []:
        row = {}
        for col, v in zip(cols, raw):
            t = col.get("type_name")
            row[col["name"]] = (int(v) if t in INTEGERS else float(v)) if v is not None and t in NUMBERS else v
        out.append(row)
    return out


def query(text, max_wait=300, every=5, sleep=time.sleep):
    """Rows as dicts. A cold warehouse takes a minute or two to start, so a pending statement is polled."""
    reply = _call("POST", "/api/2.0/sql/statements", {"warehouse_id": warehouse_id(), "statement": text,
                                                      "wait_timeout": "30s", "on_wait_timeout": "CONTINUE",
                                                      "format": "JSON_ARRAY", "disposition": "INLINE"})
    waited = 0
    while reply["status"]["state"] in ("PENDING", "RUNNING"):
        if waited >= max_wait:
            raise TimeoutError(f"statement {reply['statement_id']} still running after {max_wait} s")
        sleep(every)
        waited += every
        reply = _call("GET", f"/api/2.0/sql/statements/{reply['statement_id']}")
    if reply["status"]["state"] != "SUCCEEDED":
        err = reply["status"].get("error") or {}
        raise RuntimeError(f"statement {reply['status']['state']}: {err.get('message', err)}")
    return to_rows(reply)

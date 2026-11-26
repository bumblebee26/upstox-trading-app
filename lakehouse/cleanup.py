"""One-time: drop the tables still tied to the deleted upx-lakehouse pipeline (owner's request, 27 Nov), so the
three new pipelines can create tables with the same names. Only tables whose pipeline_id is the old one are
dropped; their data is reloaded from the landing volume. Delete this file once it has run.

  python -m lakehouse.cleanup 502749df-d1d9-4ed5-b529-7260563d5d29
"""
import json
import sys
import urllib.parse

from core import http
from lakehouse.sync import _auth, _host

SCHEMAS = ("bronze", "silver", "gold")


def drop_tables_of(pipeline_id, catalog="upx"):
    dropped = []
    for schema in SCHEMAS:
        query = urllib.parse.urlencode({"catalog_name": catalog, "schema_name": schema, "max_results": 1000})
        found = json.loads(http.request("GET", f"{_host()}/api/2.1/unity-catalog/tables?{query}", headers=_auth(),
                                        log_url=f"databricks list tables {schema}"))
        for t in found.get("tables", []):
            if t.get("pipeline_id") == pipeline_id:
                http.request("DELETE", f"{_host()}/api/2.1/unity-catalog/tables/{t['full_name']}", headers=_auth(),
                             log_url=f"databricks drop {t['full_name']}")
                dropped.append(t["full_name"])
    return dropped


if __name__ == "__main__":
    print(json.dumps({"dropped": drop_tables_of(sys.argv[1])}))

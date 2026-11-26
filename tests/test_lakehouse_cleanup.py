"""lakehouse.cleanup: drop only the tables still tied to the deleted upx-lakehouse pipeline."""
import json
import os
import unittest
from unittest import mock

from lakehouse import cleanup

OLD = "502749df-d1d9-4ed5-b529-7260563d5d29"


class CleanupTest(unittest.TestCase):
    def test_drops_only_the_old_pipelines_tables(self):
        calls = []

        def fake(method, url, **kw):
            calls.append((method, url))
            if method == "GET":
                schema = url.split("schema_name=")[1].split("&")[0]
                return json.dumps({"tables": [
                    {"full_name": f"upx.{schema}.old_one", "pipeline_id": OLD},
                    {"full_name": f"upx.{schema}.new_one", "pipeline_id": "someone-else"},
                    {"full_name": f"upx.{schema}.plain"}]}).encode()
            return b"{}"

        with mock.patch.dict(os.environ, {"DATABRICKS_HOST": "https://h", "DATABRICKS_TOKEN": "t"}), \
                mock.patch.object(cleanup.http, "request", side_effect=fake):
            dropped = cleanup.drop_tables_of(OLD)
        self.assertEqual(dropped, ["upx.bronze.old_one", "upx.silver.old_one", "upx.gold.old_one"])
        self.assertEqual([u for m, u in calls if m == "DELETE"],
                         [f"https://h/api/2.1/unity-catalog/tables/upx.{s}.old_one" for s in ("bronze", "silver", "gold")])


if __name__ == "__main__":
    unittest.main()

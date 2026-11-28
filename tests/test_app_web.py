"""lambdas/app_web.py: the app is served only at /<secret path>/<known file>; everything else is 404."""
import base64
import os
import unittest
from unittest import mock

from lambdas import app_web

SECRET = "0f3c2a9e-secret"


class RouteTest(unittest.TestCase):
    def test_known_files_under_the_secret_path(self):
        self.assertEqual(app_web.route(f"/{SECRET}/", SECRET), (200, "index.html"))
        self.assertEqual(app_web.route(f"/{SECRET}/data/desk.json", SECRET), (200, "data/desk.json"))
        self.assertEqual(app_web.route(f"/{SECRET}/data/stocks.json", SECRET), (200, "data/stocks.json"))

    def test_the_bare_secret_redirects_to_the_folder(self):
        self.assertEqual(app_web.route(f"/{SECRET}", SECRET), (302, f"/{SECRET}/"))

    def test_anything_else_is_not_found(self):
        for path in ("/", "/index.html", f"/{SECRET}x/", f"/{SECRET}/../state/x", f"/{SECRET}/data/other.json", "/a/data/desk.json"):
            self.assertEqual(app_web.route(path, SECRET)[0], 404, path)

    def test_no_secret_configured_serves_nothing(self):
        self.assertEqual(app_web.route("//", "")[0], 404)


class HandlerTest(unittest.TestCase):
    def call(self, path, method="GET", body=b"<html>", missing=False):
        s3 = mock.Mock()
        s3.exceptions.NoSuchKey = KeyError
        s3.get_object.side_effect = KeyError if missing else None
        s3.get_object.return_value = {"Body": mock.Mock(read=lambda: body)}
        env = {"APP_BUCKET": "upx-app-1", "APP_PATH": SECRET}
        with mock.patch.object(app_web, "_s3", s3), mock.patch.dict(os.environ, env):
            out = app_web.handler({"rawPath": path, "requestContext": {"http": {"method": method}}}, None)
        return out, s3

    def test_serves_the_file_with_its_type_and_safety_headers(self):
        out, s3 = self.call(f"/{SECRET}/")
        self.assertEqual(out["statusCode"], 200)
        self.assertEqual(base64.b64decode(out["body"]), b"<html>")
        self.assertEqual(out["headers"]["content-type"], "text/html; charset=utf-8")
        self.assertEqual(out["headers"]["x-frame-options"], "DENY")
        s3.get_object.assert_called_once_with(Bucket="upx-app-1", Key="app/index.html")

    def test_data_is_never_cached_long(self):
        out, _ = self.call(f"/{SECRET}/data/desk.json", body=b"{}")
        self.assertEqual(out["headers"]["cache-control"], "no-cache")

    def test_only_get_and_head(self):
        self.assertEqual(self.call(f"/{SECRET}/", method="POST")[0]["statusCode"], 405)

    def test_a_missing_file_is_404(self):
        self.assertEqual(self.call(f"/{SECRET}/data/desk.json", missing=True)[0]["statusCode"], 404)


if __name__ == "__main__":
    unittest.main()

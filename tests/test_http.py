"""core.http against a real local server: retries, 404, Retry-After, other errors."""
import http.server
import threading
import time
import unittest

from core import http as h


class _Server(http.server.ThreadingHTTPServer):
    def __init__(self, replies):
        self.replies = list(replies)  # (status, headers, body) served in order; the last one repeats
        self.hits = 0
        super().__init__(("127.0.0.1", 0), _Handler)


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        srv = self.server
        status, headers, body = srv.replies[min(srv.hits, len(srv.replies) - 1)]
        srv.hits += 1
        if status == 0:  # drop the connection without answering
            self.close_connection = True
            return
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class HttpTest(unittest.TestCase):
    def serve(self, *replies):
        srv = _Server(replies)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        return srv, f"http://127.0.0.1:{srv.server_port}/x"

    def test_returns_body(self):
        _, url = self.serve((200, {}, b'{"a": 1}'))
        self.assertEqual(h.get_json(url), {"a": 1})

    def test_retries_5xx_then_succeeds(self):
        srv, url = self.serve((503, {}, b""), (200, {}, b"ok"))
        self.assertEqual(h.request("GET", url, backoff_seconds=0), b"ok")
        self.assertEqual(srv.hits, 2)

    def test_retries_dropped_connection(self):
        srv, url = self.serve((0, {}, b""), (200, {}, b"ok"))
        self.assertEqual(h.request("GET", url, backoff_seconds=0), b"ok")
        self.assertEqual(srv.hits, 2)

    def test_404_raises_not_found_without_retry(self):
        srv, url = self.serve((404, {}, b""))
        with self.assertRaises(h.NotFound):
            h.request("GET", url, backoff_seconds=0)
        self.assertEqual(srv.hits, 1)

    def test_other_4xx_raises_at_once_with_detail(self):
        srv, url = self.serve((401, {}, b"bad token"))
        with self.assertRaisesRegex(RuntimeError, "HTTP 401.*bad token"):
            h.request("GET", url, backoff_seconds=0)
        self.assertEqual(srv.hits, 1)

    def test_429_waits_for_retry_after(self):
        srv, url = self.serve((429, {"Retry-After": "1"}, b""), (200, {}, b"ok"))
        start = time.monotonic()
        self.assertEqual(h.request("GET", url, backoff_seconds=0), b"ok")
        self.assertGreaterEqual(time.monotonic() - start, 1.0)

    def test_gives_up_after_retries(self):
        srv, url = self.serve((500, {}, b""))
        with self.assertRaisesRegex(RuntimeError, "after 3 attempts"):
            h.request("GET", url, backoff_seconds=0)
        self.assertEqual(srv.hits, 3)

    def test_log_url_hides_secret_url(self):
        _, url = self.serve((401, {}, b""))
        with self.assertRaises(RuntimeError) as ctx:
            h.request("GET", url + "?key=SECRET", log_url="redacted", backoff_seconds=0)
        self.assertNotIn("SECRET", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

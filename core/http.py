"""HTTP helper, standard library only, shared by the trader, the Lambdas and the jobs.

Retries network errors, 429 and 5xx. On 429 it waits for the server's Retry-After when given,
so the Upstox rate limit is respected even if the local limiter misjudges.
"""
import json
import logging
import time
import urllib.error
import urllib.request

log = logging.getLogger("upx")

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) upstox-trading-app/1.0"
RETRY_CODES = (429, 500, 502, 503, 504)


class NotFound(Exception):
    """404: the source has nothing at that address (a holiday, a weekend, not published yet)."""


def request(method, url, *, headers=None, data=None, retries=3, backoff_seconds=3, timeout=30, log_url=None):
    """Return the response body as bytes. Pass log_url to keep a secret URL out of logs and errors."""
    shown = log_url or url
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})}, method=method)
    last = None
    for attempt in range(1, retries + 1):
        wait = backoff_seconds * attempt
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as err:
            if err.code == 404:
                raise NotFound(shown) from err
            if err.code not in RETRY_CODES:
                raise RuntimeError(f"HTTP {err.code} from {method} {shown}: {err.read()[:300]!r}") from err
            retry_after = err.headers.get("Retry-After", "")
            if retry_after.isdigit():
                wait = max(wait, int(retry_after))
            last = f"HTTP {err.code}"
        except urllib.error.URLError as err:
            last = err.reason
        if attempt < retries:
            log.warning("%s %s failed (attempt %d/%d): %s; retrying in %ss", method, shown, attempt, retries, last, wait)
            time.sleep(wait)
    raise RuntimeError(f"{method} {shown} failed after {retries} attempts: {last}")


def get_json(url, **kwargs):
    return json.loads(request("GET", url, **kwargs))

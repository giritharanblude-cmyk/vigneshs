"""HTTP client utilities with retries, timeouts, and proper User-Agent."""
import time
import requests
from typing import Optional

DEFAULT_HEADERS = {
    "User-Agent": "SoftSkillAITrends/1.0 (+https://github.com/; research intelligence bot)",
    "Accept": "application/json, text/xml, */*",
}

MAX_RETRIES = 3
RETRY_BACKOFF = 2.0
TIMEOUT = 20


def http_get(url: str, params: Optional[dict] = None, headers: Optional[dict] = None,
             timeout: int = TIMEOUT, retries: int = MAX_RETRIES) -> Optional[requests.Response]:
    """Perform a GET request with retries and backoff."""
    hdrs = {**DEFAULT_HEADERS, **(headers or {})}
    attempt = 0
    last_err = None
    while attempt < retries:
        try:
            resp = requests.get(url, params=params, headers=hdrs, timeout=timeout)
            if resp.status_code == 200:
                return resp
            # Retry on 5xx and rate-limit (429/403/503)
            if resp.status_code in (429, 403, 500, 502, 503, 504):
                last_err = f"HTTP {resp.status_code}"
                time.sleep(RETRY_BACKOFF * (attempt + 1))
                attempt += 1
                continue
            # Other status -> no retry
            last_err = f"HTTP {resp.status_code}"
            break
        except requests.RequestException as e:
            last_err = str(e)
            time.sleep(RETRY_BACKOFF * (attempt + 1))
            attempt += 1
    if last_err:
        print(f"  [http] Failed to fetch {url}: {last_err}")
    return None


def http_get_json(url: str, params: Optional[dict] = None, headers: Optional[dict] = None
                  ) -> Optional[dict]:
    """GET a URL and parse JSON response."""
    resp = http_get(url, params=params, headers=headers)
    if resp is None:
        return None
    try:
        return resp.json()
    except ValueError:
        return None

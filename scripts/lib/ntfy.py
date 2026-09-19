"""ntfy publish helper for the paging channel (2026-08-25 cutover).

Publishes via the TOPIC path (POST {url}/{topic}?title=..&priority=..) — NOT the
JSON root endpoint — because the public route (https://matrix.example.net)
only proxies /alrt-* and /up* topic paths to ntfy; the root path is element-web.
Metadata rides in query params (not headers) so non-ASCII never hits the
latin-1-only header codec in urllib.

Auth: Bearer token (ntfy user `alerts-pub`, write-only on alrt-*).
Runbook: docs/runbooks/paging-ntfy.md
"""
from __future__ import annotations

import urllib.parse
import urllib.request


def publish(url: str, topic: str, token: str, title: str, message: str,
            priority: int = 5, tags: str = "", click: str = "",
            timeout: int = 8, retries: int = 1) -> tuple[bool, str]:
    """Send one push. Returns (ok, info). Never raises."""
    if not (url and topic):
        return False, "ntfy url/topic missing"
    params = {"title": (title or "")[:200], "priority": str(int(priority))}
    if tags:
        params["tags"] = tags
    if click:
        params["click"] = click
    full = f"{url.rstrip('/')}/{topic}?{urllib.parse.urlencode(params)}"
    body = (message or "")[:3800].encode("utf-8")  # ntfy message-size-limit is 4K
    last = "unattempted"
    for _ in range(1 + max(0, retries)):
        try:
            req = urllib.request.Request(full, data=body, method="POST")
            if token:
                req.add_header("Authorization", f"Bearer {token}")
            req.add_header("Content-Type", "text/plain; charset=utf-8")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status < 300:
                    return True, f"http {resp.status}"
                last = f"http {resp.status}"
        except Exception as e:  # noqa: BLE001 - paging path must never raise
            last = f"err {e}"
    return False, last

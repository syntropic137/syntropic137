#!/usr/bin/env python3
"""Smoke-check a running gateway: React at /, Skyline (apps/syn-ui) at /next.

Usage: python3 infra/scripts/check_gateway_next.py [BASE_URL]
       (default http://127.0.0.1:8137, the selfhost gateway port)

Asserts the serving contract from the Skyline spec (Migration plan): the React
dashboard keeps / and every non-/next path, Skyline answers /next/* with its
own index.html, its hashed assets are cacheable, and a missing Skyline chunk is
a 404 rather than an HTML fallback. Stdlib only, so CI and a laptop run it as is.
"""

from __future__ import annotations

import re
import sys
import urllib.error
import urllib.request

SKYLINE_MARK = "/next/assets/"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))


def fetch(base: str, path: str) -> tuple[int, dict[str, str], str]:
    try:
        with _opener.open(base + path, timeout=10) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read().decode("utf-8", "replace")


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8137").rstrip("/")
    failures: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("ok   " if ok else "FAIL ") + what)
        if not ok:
            failures.append(what)

    for path in ("/", "/executions/abc", "/nextish"):
        status, _, body = fetch(base, path)
        check(status == 200 and SKYLINE_MARK not in body, f"{path} -> React index (200, no {SKYLINE_MARK})")

    status, headers, _ = fetch(base, "/next")
    check(status == 301 and headers.get("location") == "/next/", "/next -> 301 /next/")

    index = ""
    for path in ("/next/", "/next/executions/abc", "/next/workflows/x/runs"):
        status, headers, body = fetch(base, path)
        check(status == 200 and SKYLINE_MARK in body, f"{path} -> Skyline index")
        check("no-cache" in headers.get("cache-control", ""), f"{path} -> Cache-Control no-cache")
        check("content-security-policy" in headers, f"{path} -> security headers kept")
        index = index or body

    entry = re.search(r'/next/assets/[^"]+\.js', index)
    check(entry is not None, "Skyline index names an entry chunk")
    if entry:
        status, headers, _ = fetch(base, entry.group(0))
        check(status == 200 and "javascript" in headers.get("content-type", ""), f"{entry.group(0)} -> 200 JS")
        check("immutable" in headers.get("cache-control", ""), "Skyline assets -> immutable cache")

    status, _, _ = fetch(base, "/next/assets/does-not-exist.js")
    check(status == 404, "missing Skyline chunk -> 404 (no HTML fallback)")

    if failures:
        print(f"\n{len(failures)} check(s) failed", file=sys.stderr)
        return 1
    print("\ngateway serves React at / and Skyline at /next")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Smoke-check a running gateway's dashboard routing (docs/syn-ui-rollout.md).

Usage: python3 infra/scripts/check_gateway_ui.py [BASE_URL] [--mode next|legacy]
       (default http://127.0.0.1:8137, the selfhost gateway port; mode next)

``--mode`` is the gateway's SYN_GATEWAY_UI:

* next (default): syn-ui owns / and every SPA path, /next and /next/* answer
  301 to the same path under /, hashed assets are cacheable, and a missing
  chunk is a 404 rather than an HTML fallback. The React dashboard is not
  served at all (its router cannot be re-based without source edits).
* legacy: the previous release's layout, React at / and syn-ui at /next.

Both modes also assert /api/v1/ still reaches the API proxy (a 502 from nginx
with no API behind it counts; an SPA index.html does not). Stdlib only, so CI
and a laptop run it as is.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

#: Mount points: apps/syn-dashboard-ui/index.html and apps/syn-ui/index.html.
REACT_MARK = '<div id="root">'
SYN_UI_MARK = '<div id="app">'
SYN_UI_ASSET_RE = r'/assets/[^"]+\.js'


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))


def fetch(base: str, path: str) -> tuple[int, dict[str, str], str]:
    try:
        with _opener.open(base + path, timeout=10) as r:
            return (
                r.status,
                {k.lower(): v for k, v in r.headers.items()},
                r.read().decode("utf-8", "replace"),
            )
    except urllib.error.HTTPError as e:
        return (
            e.code,
            {k.lower(): v for k, v in e.headers.items()},
            e.read().decode("utf-8", "replace"),
        )


def is_syn_ui(body: str, prefix: str) -> bool:
    return SYN_UI_MARK in body and REACT_MARK not in body and f'"{prefix}assets/' in body


def check_assets(base: str, index: str, prefix: str, check: Callable[[bool, str], None]) -> None:
    entry = re.search(re.escape(prefix.rstrip("/")) + SYN_UI_ASSET_RE, index)
    check(entry is not None, f"syn-ui index names an entry chunk under {prefix}assets/")
    if entry:
        status, headers, _ = fetch(base, entry.group(0))
        check(
            status == 200 and "javascript" in headers.get("content-type", ""),
            f"{entry.group(0)} -> 200 JS",
        )
        check("immutable" in headers.get("cache-control", ""), "syn-ui assets -> immutable cache")
    status, _, _ = fetch(base, f"{prefix}assets/does-not-exist.js")
    check(status == 404, "missing syn-ui chunk -> 404 (no HTML fallback)")


def check_next(base: str, check: Callable[[bool, str], None]) -> None:
    index = ""
    for path in ("/", "/executions/abc", "/workflows/x/runs", "/nextish"):
        status, headers, body = fetch(base, path)
        check(status == 200 and is_syn_ui(body, "/"), f"{path} -> syn-ui index")
        check("no-cache" in headers.get("cache-control", ""), f"{path} -> Cache-Control no-cache")
        check("content-security-policy" in headers, f"{path} -> security headers kept")
        index = index or body
    check_assets(base, index, "/", check)

    for path, target in (
        ("/next", "/"),
        ("/next/", "/"),
        ("/next/executions/abc", "/executions/abc"),
    ):
        status, headers, _ = fetch(base, path)
        check(
            status == 301 and headers.get("location") == target,
            f"{path} -> 301 {target}",
        )

    status, _, body = fetch(base, "/legacy")
    check(REACT_MARK not in body, "/legacy -> React not served in next mode")


def check_legacy(base: str, check: Callable[[bool, str], None]) -> None:
    for path in ("/", "/executions/abc", "/nextish"):
        status, _, body = fetch(base, path)
        check(status == 200 and REACT_MARK in body, f"{path} -> React index")

    status, headers, _ = fetch(base, "/next")
    check(status == 301 and headers.get("location") == "/next/", "/next -> 301 /next/")

    index = ""
    for path in ("/next/", "/next/executions/abc"):
        status, headers, body = fetch(base, path)
        check(status == 200 and is_syn_ui(body, "/next/"), f"{path} -> syn-ui index")
        check("no-cache" in headers.get("cache-control", ""), f"{path} -> Cache-Control no-cache")
        index = index or body
    check_assets(base, index, "/next/", check)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base", nargs="?", default="http://127.0.0.1:8137")
    parser.add_argument("--mode", choices=("next", "legacy"), default="next")
    args = parser.parse_args()
    base = str(args.base).rstrip("/")
    failures: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("ok   " if ok else "FAIL ") + what)
        if not ok:
            failures.append(what)

    if args.mode == "next":
        check_next(base, check)
    else:
        check_legacy(base, check)

    # The API proxy is unchanged in both modes. With no API behind the gateway
    # nginx answers 502/504; with one, the API answers. Never an SPA index,
    # which is what a lost /api/v1/ location would fall through to.
    status, _, body = fetch(base, "/api/v1/health")
    check(
        SYN_UI_MARK not in body and REACT_MARK not in body and status != 404,
        f"/api/v1/ -> proxied to the API (got {status}, not an SPA page)",
    )

    if failures:
        print(f"\n{len(failures)} check(s) failed", file=sys.stderr)
        return 1
    print(f"\ngateway routing ok (SYN_GATEWAY_UI={args.mode})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

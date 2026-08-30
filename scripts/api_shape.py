#!/usr/bin/env python3
"""Print the raw key shape of a JSON API response.

Why this exists: on 2026-08-29 I made six wrong claims in one day, and four of
them were the same mistake -- reading a field off a response that does not carry
it, getting `None`, and reporting the silence as a finding. Twice I concluded
resources were missing when they were present under a different key. Once I
inferred a response shape from line numbers in the route module and filed an
issue that had to be retracted.

Every one of those was one command away from being caught. The point of this
script is to make "look at the actual shape" cheaper than guessing, because
resolving to be more careful demonstrably did not work.

    uv run python scripts/api_shape.py http://host:8137/api/v1/workflows
    uv run python scripts/api_shape.py <url> --at workflows
    uv run python scripts/api_shape.py <url> --find sdlc-research-plan-v3

`--find` is the antidote to the specific failure: it reports which key a value
actually lives under, rather than confirming the key you assumed.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

_MAX_SAMPLE = 60


def _type_of(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return f"list[{len(value)}]"
    if isinstance(value, dict):
        return f"object[{len(value)}]"
    return type(value).__name__


def _sample(value: object) -> str:
    """A short, honest rendering. Never elided in a way that hides emptiness."""
    if isinstance(value, (dict, list)):
        return ""
    text = repr(value)
    return text if len(text) <= _MAX_SAMPLE else text[: _MAX_SAMPLE - 3] + "..."


def _describe_list(node: list[object], indent: int, path: str) -> None:
    """Every key across ALL elements, with how many elements carry it.

    Describing only element [0] recreated the exact failure this script
    exists to prevent: a field present on later elements was silently
    absent from the output, and the command still exited 0. A partial
    listing that looks complete is worse than no listing.
    """
    pad = "  " * indent
    dicts = [item for item in node if isinstance(item, dict)]
    if not dicts:
        print(f"{pad}  [0] ->")
        describe(node[0], indent + 2, f"{path}[0]")
        return
    counts: dict[str, int] = {}
    example: dict[str, object] = {}
    for item in dicts:
        for key, value in item.items():
            counts[key] = counts.get(key, 0) + 1
            if key not in example or example[key] is None:
                example[key] = value
    total = len(dicts)
    for key, seen in counts.items():
        value = example[key]
        sample = _sample(value)
        suffix = f" = {sample}" if sample else ""
        # The count is the point: "3/5" says the key is NOT universal, which
        # is precisely what a first-element-only view hides.
        where = "" if seen == total else f"  [in {seen}/{total}]"
        print(f"{pad}  {key}: {_type_of(value)}{suffix}{where}")
    if len(dicts) != len(node):
        print(f"{pad}  ({len(node) - len(dicts)} non-object element(s) not summarized)")


def describe(node: object, indent: int = 0, path: str = "") -> None:
    """Print every key with its type and a value sample. No filtering."""
    pad = "  " * indent
    if isinstance(node, dict):
        if not node:
            print(f"{pad}(empty object)")
            return
        for key, value in node.items():
            sample = _sample(value)
            suffix = f" = {sample}" if sample else ""
            print(f"{pad}{key}: {_type_of(value)}{suffix}")
            if isinstance(value, dict):
                describe(value, indent + 1, f"{path}.{key}")
            elif isinstance(value, list) and value:
                _describe_list(value, indent + 1, f"{path}.{key}")
    elif isinstance(node, list):
        if not node:
            print(f"{pad}(empty list)")
            return
        print(f"{pad}list of {len(node)}")
        _describe_list(node, indent, path)
    else:
        print(f"{pad}{_type_of(node)} = {_sample(node)}")


def _matches(haystack: str, needle: str, *, exact: bool) -> bool:
    """Substring by default; whole-value when exact.

    Substring alone reports `foo` present when only `foobar` exists, and
    the exit code is used as a presence check.
    """
    return haystack == needle if exact else needle in haystack


def find_value(node: object, needle: str, path: str = "$", *, exact: bool = False) -> list[str]:
    """Every path whose value contains `needle`.

    This answers the question I kept getting wrong: not "is the value under
    the key I assumed?" but "which key is it actually under?"
    """
    hits: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            # Keys too. Saying "does not appear anywhere" while never having
            # looked at a key is the same false-absence this script exists to
            # stop, and a field NAME is the thing most often searched for.
            if _matches(key, needle, exact=exact):
                hits.append(f"{path}.{key}  (as a key)")
            hits.extend(find_value(value, needle, f"{path}.{key}", exact=exact))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            hits.extend(find_value(value, needle, f"{path}[{index}]", exact=exact))
    elif _matches(str(node), needle, exact=exact):
        hits.append(f"{path} = {node!r}")
    return hits


def _fetch(url: str, timeout: float) -> Any:  # noqa: ANN401 - arbitrary JSON
    with urllib.request.urlopen(url, timeout=timeout) as response:
        body = response.read()
        content_type = response.headers.get("Content-Type", "")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        # The SPA catch-all serves HTML for unknown paths and returns 200, so a
        # decode failure here usually means the path is wrong, not the server.
        head = body[:120].decode("utf-8", errors="replace")
        print(f"not JSON (Content-Type: {content_type or 'unset'})", file=sys.stderr)
        print(f"first bytes: {head!r}", file=sys.stderr)
        raise SystemExit(2) from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--at", help="Descend into this top-level key first.")
    parser.add_argument("--find", help="Report which key path holds this value (substring).")
    parser.add_argument(
        "--find-exact",
        help="Like --find but the value must match WHOLE. Substring search reports\n"
        "'foo' present when only 'foobar' exists, which is wrong if you are\n"
        "using the exit code as a presence check.",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    try:
        payload = _fetch(args.url, args.timeout)
    except urllib.error.URLError as exc:
        print(f"request failed: {exc}", file=sys.stderr)
        return 2

    print(f"GET {args.url}")
    print()

    # --at is applied FIRST, always. It used to run only when --find was
    # absent, so `--at missing --find x` silently searched the whole payload
    # and could exit 0 on a match outside the subtree the caller asked about.
    node = payload
    if args.at:
        if not isinstance(payload, dict) or args.at not in payload:
            available = sorted(payload) if isinstance(payload, dict) else "(not an object)"
            print(f"no top-level key {args.at!r}. Available: {available}", file=sys.stderr)
            return 1
        node = payload[args.at]
        print(f"(at {args.at})")

    needle = args.find_exact or args.find
    if needle:
        exact = args.find_exact is not None
        hits = find_value(node, needle, exact=exact)
        scope = f" under {args.at}" if args.at else ""
        if not hits:
            kind = "exactly" if exact else "anywhere"
            print(f"{needle!r} does not appear {kind}{scope} in this response.")
            return 1
        print(f"{needle!r} appears at:")
        for hit in hits:
            print(f"  {hit}")
        return 0

    describe(node)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

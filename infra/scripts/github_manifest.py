#!/usr/bin/env python3
"""
GitHub App Manifest Flow — one-click GitHub App creation for Syn137.

Implements the GitHub App Manifest flow:
https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-from-a-manifest

This module is stdlib-only (no third-party dependencies) so it can run
before ``uv sync`` has been executed.

Usage (standalone):
    python infra/scripts/github_manifest.py

Usage (from setup.py):
    from github_manifest import run_manifest_flow
    result = run_manifest_flow(app_name="syntropic137", ...)
"""

from __future__ import annotations

import html
import http.server
import json
import secrets
import socket
import stat
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent.resolve()
SECRETS_DIR = SCRIPT_DIR.parent / "docker" / "secrets"
TEMPLATE_DIR = SCRIPT_DIR / "templates"

GITHUB_BASE = "https://github.com"
GITHUB_API = "https://api.github.com"

# Syn137's required permissions and events
DEFAULT_PERMISSIONS: dict[str, str] = {
    "contents": "write",
    "pull_requests": "write",
    "actions": "read",
    "checks": "write",
    "statuses": "write",
    "issues": "write",
    "metadata": "read",
}

DEFAULT_EVENTS: list[str] = [
    "workflow_run",
    "workflow_job",
    "check_run",
    "check_suite",
    "pull_request",
    "pull_request_review",
    "pull_request_review_comment",
    "push",
    "commit_comment",
    "status",
    "issues",
    "issue_comment",
    "create",
    "delete",
    "label",
    # NOTE: "installation" and "installation_repositories" are app-level
    # events managed by GitHub automatically — including them in a manifest
    # causes "Default events unsupported" validation errors.
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    """Find an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _api_request(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Make an API request and return parsed JSON (stdlib only)."""
    hdrs = {"Accept": "application/vnd.github+json", **(headers or {})}
    if data is not None:
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def _set_secure_permissions(path: Path) -> None:
    """Set file permissions to owner read/write only (600)."""
    with suppress(OSError, AttributeError):
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


# ---------------------------------------------------------------------------
# Manifest Builder
# ---------------------------------------------------------------------------


def build_manifest(
    app_name: str,
    redirect_url: str,
    webhook_url: str | None = None,
    setup_url: str | None = None,
) -> dict[str, Any]:
    """Build the GitHub App manifest JSON with Syn137's required permissions.

    Args:
        app_name: Name for the GitHub App (e.g. "syntropic137").
        redirect_url: Local callback URL for the OAuth redirect.
        webhook_url: Optional webhook delivery URL.  When *None* the
            webhook is created with an inactive hook (no URL required).
        setup_url: Optional setup URL for post-installation redirect.
            When provided, GitHub redirects here after installation
            with ``installation_id`` as a query parameter.
    """
    manifest: dict[str, Any] = {
        "name": app_name,
        "url": "https://github.com/syntropic137/syntropic137",
        "redirect_url": redirect_url,
        "public": False,
        "default_permissions": DEFAULT_PERMISSIONS,
        "default_events": DEFAULT_EVENTS,
    }
    # GitHub rejects hook_attributes with a blank URL.  Only include the
    # key when we actually have a webhook endpoint; otherwise the app is
    # created with webhooks disabled (can be configured later).
    if webhook_url:
        manifest["hook_attributes"] = {"url": webhook_url, "active": True}
    if setup_url:
        manifest["setup_url"] = setup_url
    return manifest


# ---------------------------------------------------------------------------
# Local Callback Server
# ---------------------------------------------------------------------------

# Module-level mutable state shared between the callback handler and the
# waiting thread.  This module is NOT thread-safe — only one manifest flow
# should run at a time per process (which is the expected CLI usage).
_callback_result: dict[str, str | None] = {"code": None, "error": None}
_callback_event = threading.Event()

# Installation callback state (set when user installs the app).
_installation_result: dict[str, str | None] = {"installation_id": None}
_installation_event = threading.Event()

# CSRF state token — set before the browser flow, validated on callback.
_expected_state: str | None = None

# Shared server references for lifecycle management across callbacks.
_callback_server: http.server.HTTPServer | None = None
_form_server: http.server.HTTPServer | None = None


class _ManifestCallbackHandler(http.server.BaseHTTPRequestHandler):
    """Receives the redirect from GitHub carrying the temporary code."""

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/callback":
            self._handle_manifest_callback(params)
        elif parsed.path == "/installed":
            self._handle_installation_callback(params)
        else:
            self.send_error(404)
            return

    def _handle_manifest_callback(self, params: dict[str, list[str]]) -> None:
        """Handle the manifest creation redirect (``/callback?code=...``)."""
        # Validate CSRF state token
        state = params.get("state", [None])[0]
        if _expected_state and state != _expected_state:
            _callback_result["error"] = "state_mismatch"
            self.send_response(403)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h1>Error</h1><p>State mismatch (possible CSRF).</p></body></html>"
            )
            _callback_event.set()
            return

        code = params.get("code", [None])[0]
        if code:
            _callback_result["code"] = code
            body = _load_success_page()
        else:
            error = params.get("error", ["unknown"])[0]
            _callback_result["error"] = error
            body = (
                "<html><body><h1>Error</h1>"
                f"<p>GitHub returned an error: <code>{html.escape(str(error))}</code></p>"
                "<p>Close this tab and check your terminal.</p>"
                "</body></html>"
            )

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())
        _callback_event.set()

    def _handle_installation_callback(self, params: dict[str, list[str]]) -> None:
        """Handle the post-installation redirect (``/installed?installation_id=...``)."""
        installation_id = params.get("installation_id", [None])[0]
        if installation_id:
            _installation_result["installation_id"] = installation_id
            body = _load_installation_success_page(installation_id)
        else:
            body = (
                "<html><body><h1>Installation</h1>"
                "<p>No installation ID received. Check your terminal.</p>"
                "</body></html>"
            )

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())
        _installation_event.set()

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default request logging."""


def _load_success_page() -> str:
    """Load the HTML success page template, falling back to inline HTML."""
    template = TEMPLATE_DIR / "manifest_success.html"
    if template.exists():
        return template.read_text()
    return (
        "<html><body style='font-family:system-ui;max-width:600px;margin:40px auto;text-align:center'>"
        "<h1>GitHub App Created!</h1>"
        "<p>Return to your terminal to continue setup.</p>"
        "</body></html>"
    )


def _load_installation_success_page(installation_id: str) -> str:
    """Load the installation success page, substituting the installation ID."""
    template = TEMPLATE_DIR / "installation_success.html"
    if template.exists():
        content = template.read_text()
        return content.replace("{{INSTALLATION_ID}}", html.escape(installation_id))
    return (
        "<html><body style='font-family:system-ui;max-width:600px;margin:40px auto;text-align:center'>"
        "<h1>Installation Complete!</h1>"
        f"<p>Installation ID: <code>{html.escape(installation_id)}</code></p>"
        "<p>Return to your terminal to continue setup.</p>"
        "</body></html>"
    )


def wait_for_callback(port: int, timeout: int = 300) -> str:
    """Start a local HTTP server, wait for GitHub's redirect, return the code.

    The server is kept alive after receiving the code so it can also handle
    the post-installation ``/installed`` redirect.  Call
    :func:`shutdown_callback_server` when completely done.

    Args:
        port: TCP port to listen on.
        timeout: Maximum seconds to wait for the redirect.

    Returns:
        The temporary ``code`` from GitHub.

    Raises:
        TimeoutError: If the callback isn't received within *timeout*.
        RuntimeError: If GitHub returns an error instead of a code.
    """
    global _callback_server

    _callback_result["code"] = None
    _callback_result["error"] = None
    _callback_event.clear()
    _installation_result["installation_id"] = None
    _installation_event.clear()

    server = http.server.HTTPServer(("127.0.0.1", port), _ManifestCallbackHandler)
    _callback_server = server
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    if not _callback_event.wait(timeout=timeout):
        shutdown_callback_server()
        raise TimeoutError(
            f"No callback received within {timeout}s. "
            "Did you complete the GitHub App creation in your browser?"
        )

    if _callback_result["error"]:
        shutdown_callback_server()
        raise RuntimeError(f"GitHub returned error: {_callback_result['error']}")

    code = _callback_result["code"]
    assert code is not None
    return code


def wait_for_installation(timeout: int = 180) -> str | None:
    """Wait for the post-installation redirect carrying the installation ID.

    Should be called after :func:`wait_for_callback` — the same server
    handles both endpoints.

    Args:
        timeout: Maximum seconds to wait for the installation callback.

    Returns:
        The installation ID string, or *None* if the timeout expires
        (the user can still enter it manually).
    """
    if not _installation_event.wait(timeout=timeout):
        return None
    return _installation_result.get("installation_id")


def shutdown_callback_server() -> None:
    """Gracefully shut down all local HTTP servers (callback + form)."""
    global _callback_server, _form_server
    for ref in (_callback_server, _form_server):
        if ref is not None:
            with suppress(Exception):
                ref.shutdown()
    _callback_server = None
    _form_server = None


# ---------------------------------------------------------------------------
# Code Exchange
# ---------------------------------------------------------------------------


def exchange_code(code: str) -> dict[str, Any]:
    """Exchange the temporary code for full app credentials.

    Calls ``POST /app-manifests/{code}/conversions`` — no authentication
    required.

    Returns a dict containing (among others):
        id, slug, pem, webhook_secret, client_id, client_secret,
        owner, name, html_url
    """
    url = f"{GITHUB_API}/app-manifests/{code}/conversions"
    return _api_request(url, method="POST", data=b"")


# ---------------------------------------------------------------------------
# Credential Storage
# ---------------------------------------------------------------------------


def save_credentials(
    credentials: dict[str, Any],
    secrets_dir: Path | None = None,
) -> dict[str, str]:
    """Persist the credentials returned by :func:`exchange_code`.

    Saves:
    - ``github-private-key.pem`` — the RSA private key
    - ``github-webhook-secret.txt`` — the webhook secret
    - ``github-client-secret.txt`` — the OAuth client secret

    Returns a summary dict with paths written.
    """
    sdir = secrets_dir or SECRETS_DIR
    sdir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}

    # Private key
    pem_path = sdir / "github-private-key.pem"
    pem_path.write_text(credentials["pem"])
    _set_secure_permissions(pem_path)
    written["pem"] = str(pem_path)

    # Webhook secret
    ws_path = sdir / "github-webhook-secret.txt"
    ws_path.write_text(credentials.get("webhook_secret", ""))
    _set_secure_permissions(ws_path)
    written["webhook_secret"] = str(ws_path)

    # Client secret (useful for OAuth user flows later)
    cs_path = sdir / "github-client-secret.txt"
    cs_path.write_text(credentials.get("client_secret", ""))
    _set_secure_permissions(cs_path)
    written["client_secret"] = str(cs_path)

    return written


# ---------------------------------------------------------------------------
# Installation Helpers
# ---------------------------------------------------------------------------


def open_install_page(slug: str) -> str:
    """Open the browser to the app's installation page.

    Returns the URL that was opened.
    """
    url = f"{GITHUB_BASE}/apps/{slug}/installations/new"
    webbrowser.open(url)
    return url


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_manifest_flow(
    app_name: str,
    webhook_url: str | None = None,
    secrets_dir: Path | None = None,
    org: str | None = None,
) -> dict[str, Any]:
    """Run the full GitHub App Manifest flow end-to-end.

    1. Build manifest JSON with Syn137 permissions.
    2. Start a local callback server on an ephemeral port.
    3. Open the user's browser to the GitHub manifest creation page.
    4. Wait for the redirect carrying the temporary ``code``.
    5. Exchange the code for credentials via the GitHub API.
    6. Persist credentials to disk.

    Args:
        app_name: Desired name for the GitHub App.
        webhook_url: Optional webhook delivery URL.
        secrets_dir: Where to save secrets (default: ``infra/docker/secrets``).
        org: GitHub organization slug.  When provided the app is created
            under the org rather than the user's personal account.

    Returns:
        A dict with at least ``id``, ``slug``, ``pem``, ``html_url``, and
        a ``_saved`` key mapping to the written file paths.
    """
    port = _find_free_port()
    redirect_url = f"http://127.0.0.1:{port}/callback"
    setup_url = f"http://127.0.0.1:{port}/installed"

    manifest = build_manifest(
        app_name=app_name,
        redirect_url=redirect_url,
        webhook_url=webhook_url,
        setup_url=setup_url,
    )
    manifest_json = json.dumps(manifest)

    # Build the target URL — org or personal
    if org:
        create_url = f"{GITHUB_BASE}/organizations/{org}/settings/apps/new"
    else:
        create_url = f"{GITHUB_BASE}/settings/apps/new"

    # We need to POST the manifest to GitHub via a form in the browser.
    # The simplest cross-platform approach is to open a tiny local HTML page
    # that auto-submits the form.
    global _expected_state
    state = secrets.token_urlsafe(16)
    _expected_state = state
    form_html = _build_autosubmit_form(create_url, manifest_json, state)

    # Serve the auto-submit page, then reuse the same server for callback
    form_port = _find_free_port()
    form_url = f"http://127.0.0.1:{form_port}/start"
    _serve_form_page(form_port, form_html)

    print(f"  Opening browser to create GitHub App '{app_name}'...")
    print(f"  (If the browser doesn't open, visit: {form_url})")
    webbrowser.open(form_url)

    print("  Waiting for GitHub to redirect back...")
    code = wait_for_callback(port, timeout=300)

    print("  Exchanging code for credentials...")
    credentials = exchange_code(code)

    print("  Saving credentials...")
    saved = save_credentials(credentials, secrets_dir=secrets_dir)
    credentials["_saved"] = saved

    print(f"  GitHub App '{credentials.get('slug', app_name)}' created successfully!")

    # Open the installation page and wait for the post-install redirect.
    slug = credentials.get("slug", app_name)
    print()
    print(f"  Opening installation page for '{slug}'...")
    open_install_page(slug)

    print("  Waiting for installation callback (up to 3 minutes)...")
    installation_id = wait_for_installation(timeout=180)
    shutdown_callback_server()

    if installation_id:
        credentials["installation_id"] = installation_id
        print(f"  Installation ID detected: {installation_id}")
    else:
        credentials["installation_id"] = None
        print("  Installation callback not received (timed out).")
        print("  You can enter the installation ID manually.")

    return credentials


# ---------------------------------------------------------------------------
# Auto-submit form (opens in browser to POST manifest to GitHub)
# ---------------------------------------------------------------------------


def _build_autosubmit_form(
    action_url: str,
    manifest_json: str,
    state: str,
) -> str:
    """Build an HTML page that auto-submits the manifest to GitHub."""
    # Escape for safe embedding in an HTML attribute
    escaped_manifest = html.escape(manifest_json, quote=True)
    escaped_state = html.escape(state, quote=True)
    return f"""\
<!DOCTYPE html>
<html>
<head><title>Creating GitHub App...</title></head>
<body style="font-family:system-ui;max-width:600px;margin:80px auto;text-align:center">
  <h2>Redirecting to GitHub...</h2>
  <p>If you are not redirected automatically,
     click the button below.</p>
  <form id="manifest-form" method="post" action="{html.escape(action_url)}">
    <input type="hidden" name="manifest" value='{escaped_manifest}'>
    <input type="hidden" name="state" value="{escaped_state}">
    <button type="submit" style="font-size:1.2em;padding:10px 24px;cursor:pointer">
      Create GitHub App
    </button>
  </form>
  <script>document.getElementById('manifest-form').submit();</script>
</body>
</html>"""


class _FormPageHandler(http.server.BaseHTTPRequestHandler):
    """Serves the auto-submit form exactly once, then stops."""

    _html: str = ""

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(self._html.encode())

    def log_message(self, format: str, *args: Any) -> None:
        pass


def _serve_form_page(port: int, form_html: str) -> None:
    """Start a background server that serves the form HTML on ``/start``."""
    global _form_server

    class Handler(_FormPageHandler):
        _html = form_html

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    _form_server = server
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()


# ---------------------------------------------------------------------------
# CLI entry point (for standalone testing)
# ---------------------------------------------------------------------------


def main() -> None:
    """Interactive CLI for the manifest flow."""
    print()
    print("=" * 55)
    print("  GitHub App Manifest Flow — Syn137 Setup")
    print("=" * 55)
    print()

    app_name = input("  App name [syntropic137]: ").strip() or "syntropic137"
    org = input("  GitHub org (blank for personal): ").strip() or None
    webhook_url = input("  Webhook URL (blank to skip): ").strip() or None

    print()
    try:
        result = run_manifest_flow(
            app_name=app_name,
            webhook_url=webhook_url,
            org=org,
        )
    except TimeoutError as exc:
        print(f"\n  [FAIL] {exc}")
        sys.exit(1)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        print(f"\n  [FAIL] GitHub API error {exc.code}: {body}")
        sys.exit(1)
    except RuntimeError as exc:
        print(f"\n  [FAIL] {exc}")
        sys.exit(1)

    print()
    print(f"  App ID:   {result['id']}")
    print(f"  Slug:     {result.get('slug', 'N/A')}")
    print(f"  HTML URL: {result.get('html_url', 'N/A')}")
    print()

    install_id = result.get("installation_id")
    if install_id:
        print(f"  Installation ID: {install_id}")
        print("  (Installation IDs are resolved dynamically at runtime — no .env entry needed)")
    else:
        print("  Installation ID was not auto-detected.")
        print("  (Installation IDs are resolved dynamically at runtime — no .env entry needed)")

    print()
    print("  Done! Run 'python infra/scripts/secrets_setup.py check' to verify.")


if __name__ == "__main__":
    main()

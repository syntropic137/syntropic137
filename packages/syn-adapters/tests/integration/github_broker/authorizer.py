"""S2 spike stand-in for the grant-keyed token-injector (#1735, plan D4).

Envoy's ext_authz asks this for every GitHub request. It exchanges a
capability for the real token, and nothing else:

- git authority: no credential -> 401 + ``WWW-Authenticate: Basic`` (git only
  offers a credential after that challenge); a Basic password equal to the git
  capability, on a granted ``owner/repo`` -> the real token for THAT repo;
  anything else -> 403.
- github.com / api.github.com: ``token``/``Bearer`` equal to the gh
  capability -> the one real gh token; no credential -> 401; else 403.

PR 4 puts this behaviour in docker/token-injector. Grants arrive as JSON in
``S2_GRANTS``: {"git_capability", "git_tokens": {owner/repo: token},
"gh_capability", "gh_token"}.
"""

from __future__ import annotations

import base64
import json
import os
import re
from http.server import BaseHTTPRequestHandler, HTTPServer

GRANTS = json.loads(os.environ["S2_GRANTS"])
GIT_AUTHORITY = "github-git.broker"
GH_AUTHORITIES = {"github.com", "api.github.com"}
_REPO = re.compile(r"^/([^/]+)/([^/]+?)(?:\.git)?(?:/|$)")


class Authorizer(BaseHTTPRequestHandler):
    def __getattr__(self, name: str):  # every method, as docker/token-injector does
        if name.startswith("do_"):
            return self._check
        raise AttributeError(name)

    def _check(self) -> None:
        host = self.headers.get("host", "").split(":")[0].lower()
        auth = self.headers.get("authorization", "")
        if host == GIT_AUTHORITY:
            self._git(auth)
        elif host in GH_AUTHORITIES:
            self._gh(auth)
        else:
            self._reply(403)

    def _git(self, auth: str) -> None:
        if not auth:
            self._reply(401, {"WWW-Authenticate": 'Basic realm="GitHub"'})
            return
        match = _REPO.match(self.path)
        scheme, _, param = auth.partition(" ")
        if scheme.lower() != "basic" or match is None:
            self._reply(403)
            return
        _, _, password = base64.b64decode(param).decode().partition(":")
        token = GRANTS["git_tokens"].get(f"{match[1]}/{match[2]}")
        if password != GRANTS["git_capability"] or token is None:
            self._reply(403)
            return
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        self._reply(200, {"authorization": f"Basic {basic}"})

    def _gh(self, auth: str) -> None:
        scheme, _, param = auth.partition(" ")
        if not auth:
            self._reply(401)
        elif scheme.lower() in ("token", "bearer") and param == GRANTS["gh_capability"]:
            self._reply(200, {"authorization": f"token {GRANTS['gh_token']}"})
        else:
            self._reply(403)

    def _reply(self, status: int, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("content-length", "0")
        self.end_headers()


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", int(os.environ.get("S2_PORT", "9002"))), Authorizer).serve_forever()

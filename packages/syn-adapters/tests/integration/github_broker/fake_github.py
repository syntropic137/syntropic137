"""Fake GitHub for the S2 spike (#1735).

Records every request it receives to /out/requests.jsonl (authority, method,
path, authorization) so the test can assert which REAL token arrived. Serves
git smart HTTP for the repositories below through ``git http-backend``, and a
minimal JSON answer for the REST and GraphQL APIs: the spike asserts that gh's
requests arrive carrying the right token, not that gh is satisfied.

Repositories: o/r (with submodules libs/a -> https://github.com/o/sub-a and
libs/b -> git@github.com:o/sub-b.git), o/sub-a, o/sub-b, o/unlisted.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(os.environ.get("S2_GIT_ROOT", "/srv/git"))
LOG = Path(os.environ.get("S2_OUT", "/out")) / "requests.jsonl"
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "s2", "GIT_AUTHOR_EMAIL": "s2@example.invalid",
           "GIT_COMMITTER_NAME": "s2", "GIT_COMMITTER_EMAIL": "s2@example.invalid",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, check=True,
                          capture_output=True, text=True).stdout.strip()


def _seed(name: str, gitlinks: dict[str, tuple[str, str]] | None = None) -> str:
    bare = ROOT / f"{name}.git"
    _git("init", "-q", "--bare", "-b", "main", str(bare))
    _git("config", "http.receivepack", "true", cwd=bare)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        _git("init", "-q", "-b", "main", str(work))
        (work / "README.md").write_text(f"{name}\n")
        _git("add", "README.md", cwd=work)
        if gitlinks:
            (work / ".gitmodules").write_text("".join(
                f'[submodule "{path}"]\n\tpath = {path}\n\turl = {url}\n'
                for path, (url, _) in gitlinks.items()))
            _git("add", ".gitmodules", cwd=work)
            for path, (_, sha) in gitlinks.items():
                _git("update-index", "--add", "--cacheinfo", f"160000,{sha},{path}", cwd=work)
        _git("commit", "-q", "-m", "seed", cwd=work)
        _git("push", "-q", str(bare), "main", cwd=work)
        return _git("rev-parse", "HEAD", cwd=work)


def seed() -> None:
    sub_a = _seed("o/sub-a")
    sub_b = _seed("o/sub-b")
    _seed("o/unlisted")
    _seed("o/r", {"libs/a": ("https://github.com/o/sub-a", sub_a),
                  "libs/b": ("git@github.com:o/sub-b.git", sub_b)})


class FakeGitHub(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __getattr__(self, name: str):
        if name.startswith("do_"):
            return self._handle
        raise AttributeError(name)

    def _body(self) -> bytes:
        if self.headers.get("transfer-encoding", "").lower() == "chunked":
            chunks = []
            while (size := int(self.rfile.readline().split(b";")[0], 16)) > 0:
                chunks.append(self.rfile.read(size))
                self.rfile.readline()
            self.rfile.readline()
            return b"".join(chunks)
        return self.rfile.read(int(self.headers.get("content-length") or 0))

    def _handle(self) -> None:
        body = self._body()
        with LOG.open("a") as log:
            log.write(json.dumps({"authority": self.headers.get("host", ""), "method": self.command,
                                  "path": self.path, "authorization": self.headers.get("authorization")}) + "\n")
        path, _, query = self.path.partition("?")
        if "/info/refs" in path or path.endswith(("/git-upload-pack", "/git-receive-pack")):
            self._git_backend(path, query, body)
        else:
            self._send(200, b'{"data": {}}', "application/json")

    def _git_backend(self, path: str, query: str, body: bytes) -> None:
        owner, repo, rest = path.lstrip("/").split("/", 2)
        repo = repo.removesuffix(".git")
        env = {**GIT_ENV, "GIT_PROJECT_ROOT": str(ROOT), "GIT_HTTP_EXPORT_ALL": "1",
               "PATH_INFO": f"/{owner}/{repo}.git/{rest}", "QUERY_STRING": query,
               "REQUEST_METHOD": self.command, "REMOTE_USER": "s2",
               "CONTENT_TYPE": self.headers.get("content-type", ""),
               "CONTENT_LENGTH": str(len(body)),
               "HTTP_CONTENT_ENCODING": self.headers.get("content-encoding", ""),
               "GIT_PROTOCOL": self.headers.get("git-protocol", "")}
        out = subprocess.run(["git", "http-backend"], input=body, env=env, capture_output=True,
                             check=False).stdout
        head, _, payload = out.partition(b"\r\n\r\n")
        status, ctype = 200, "application/octet-stream"
        for line in head.decode().split("\r\n"):
            key, _, value = line.partition(":")
            if key.lower() == "status":
                status = int(value.split()[0])
            elif key.lower() == "content-type":
                ctype = value.strip()
        self._send(status, payload, ctype)

    def _send(self, status: int, payload: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    seed()
    LOG.touch()
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("S2_PORT", "8080"))), FakeGitHub).serve_forever()

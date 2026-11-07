"""Minimal LOCAL package index for the contained attack demo (stdlib only).

Serves the distribution files in PACKAGES_DIR as:
  /simple/                 PEP 503 project list
  /simple/<name>/          PEP 503 file links (with sha256 fragments)
  /files/<filename>        the files themselves
  /pypi/<name>/json        PyPI-JSON-compatible metadata (upload time = file mtime)

There is deliberately NO upload endpoint and no client code that talks to any
public registry. "Publishing" a package in the lab means copying a file into
PACKAGES_DIR on the lab host. Nothing in this lab can register a name on PyPI.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PACKAGES_DIR = Path(os.environ.get("PACKAGES_DIR", "/packages"))
_NORM = re.compile(r"[-_.]+")
_SPLIT = re.compile(r"^(?P<name>.+?)-(?P<version>\d[^-]*?)(?:-.*)?(?:\.tar\.gz|\.zip|\.whl)$")


def norm(n: str) -> str:
    return _NORM.sub("-", n).lower()


def inventory() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for f in sorted(PACKAGES_DIR.glob("*")):
        m = _SPLIT.match(f.name)
        if not m or not f.is_file():
            continue
        data = f.read_bytes()
        out.setdefault(norm(m.group("name")), []).append({
            "filename": f.name,
            "version": m.group("version"),
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "upload_time_iso_8601": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
        })
    return out


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "text/html") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        inv = inventory()
        parts = [p for p in self.path.split("?")[0].split("/") if p]
        if parts == ["simple"]:
            links = "".join(f'<a href="/simple/{n}/">{n}</a><br>' for n in sorted(inv))
            return self._send(200, f"<html><body>{links}</body></html>".encode())
        if len(parts) == 2 and parts[0] == "simple":
            files = inv.get(norm(parts[1]))
            if not files:
                return self._send(404, b"not found")
            links = "".join(f'<a href="/files/{html.escape(f["filename"])}#sha256={f["sha256"]}">{html.escape(f["filename"])}</a><br>' for f in files)
            return self._send(200, f"<html><body>{links}</body></html>".encode())
        if len(parts) == 2 and parts[0] == "files":
            p = PACKAGES_DIR / parts[1]
            if p.is_file() and p.parent == PACKAGES_DIR:
                return self._send(200, p.read_bytes(), "application/octet-stream")
            return self._send(404, b"not found")
        if len(parts) == 3 and parts[0] == "pypi" and parts[2] == "json":
            files = inv.get(norm(parts[1]))
            if not files:
                return self._send(404, b'{"message": "Not Found"}', "application/json")
            releases: dict[str, list] = {}
            for f in files:
                releases.setdefault(f["version"], []).append(f)
            body = {"info": {"name": parts[1], "version": files[-1]["version"], "summary": "local lab index"}, "releases": releases}
            return self._send(200, json.dumps(body).encode(), "application/json")
        return self._send(404, b"not found")

    def log_message(self, fmt, *args) -> None:
        sys.stderr.write("[registry] " + (fmt % args) + "\n")


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    host = os.environ.get("HOST", "0.0.0.0")
    PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[registry] serving {PACKAGES_DIR} on {host}:{port} (local only, no upload endpoint)", file=sys.stderr)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()

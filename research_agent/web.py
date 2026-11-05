from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .briefs import daily_brief, render_markdown
from .retrieval import answer
from .store import Store

STATIC = Path(__file__).parent / "static"


def make_handler(database: str | Path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ResearchIntelligence/0.1"

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *_):
            # Questions and source material are deliberately not logged.
            pass

        def _respond(self, payload, status=200, content_type="application/json; charset=utf-8"):
            body = json.dumps(payload).encode() if content_type.startswith("application/json") else payload
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def _allowed(self) -> bool:
            port = self.server.server_port
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            if host not in hosts or (origin is not None and origin not in {f"http://{h}" for h in hosts}):
                self._respond({"error": "Only same-origin loopback requests are permitted"}, 403)
                return False
            return True

        def do_GET(self):
            if not self._allowed():
                return
            path = urlsplit(self.path).path
            static = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8")}
            if path in static:
                filename, content_type = static[path]
                self._respond((STATIC / filename).read_bytes(), content_type=content_type)
                return
            with Store(database) as store:
                if path == "/api/status":
                    self._respond(store.stats())
                elif path == "/api/papers":
                    self._respond({"papers": store.all()[:100], "total": store.count()})
                elif path == "/api/brief":
                    brief = daily_brief(store)
                    self._respond({**brief, "markdown": render_markdown(brief)})
                else:
                    self._respond({"error": "Not found"}, 404)

        def do_POST(self):
            if not self._allowed():
                return
            if urlsplit(self.path).path != "/api/answer":
                self._respond({"error": "Not found"}, 404)
                return
            if self.headers.get("X-Research-Request") != "1" or self.headers.get_content_type() != "application/json":
                self._respond({"error": "JSON and a same-origin request header are required"}, 403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= 12000:
                    raise ValueError("Request body must contain 1–12000 bytes")
                self.connection.settimeout(5)
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict) or set(payload) != {"query"}:
                    raise ValueError("Expected a query field only")
                with Store(database) as store:
                    self._respond(answer(store, payload["query"]))
            except (ValueError, OSError) as error:
                self._respond({"error": "Invalid request: use a question of 1–3000 characters"}, 400)

    return Handler


def serve(database: str | Path, port: int = 8765):
    if not 1024 <= port <= 65535:
        raise ValueError("Choose a port between 1024 and 65535")
    with Store(database):
        pass
    with HTTPServer(("127.0.0.1", port), make_handler(database)) as server:
        print(f"Research console: http://127.0.0.1:{port} (local only; Ctrl-C to stop)", flush=True)
        server.serve_forever()

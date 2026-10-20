"""Read-only localhost viewer for the canonical project architecture."""

from __future__ import annotations

import argparse
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .project_architecture import ArchitectureError, load_architecture
from .runtime_revision import LOADED_CODE_REVISION


STATIC_TYPES = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
    "cytoscape.min.js": "text/javascript; charset=utf-8",
}
MAX_REJECT_BODY_BYTES = 4096
REJECT_BODY_TIMEOUT_SECONDS = 1.0


def server_identity(workspace_root: Path) -> str:
    """Input: workspace Path. Output: identity str. Bind viewer reuse to workspace and loaded code."""
    digest = sha256(str(workspace_root.resolve()).encode("utf-8")).hexdigest()[:16]
    return f"brainworkflow-architecture-v2:{digest}:{LOADED_CODE_REVISION}"


def make_server(workspace_root: Path, port: int = 8766) -> ThreadingHTTPServer:
    """Input: workspace Path and port. Output: local read-only HTTP server."""
    root = workspace_root.resolve()
    assets = root / "skills-and-workflows" / "BrainWorkflow" / "management" / "architecture"
    milestone = root / "milestone.md"
    identity = server_identity(root)

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: dict[str, object]) -> None:
            self._reply(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self) -> None:
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                self.send_error(403, "Invalid local host")
                return
            request_path = urlsplit(self.path).path
            if request_path == "/api/health":
                self._json(200, {"identity": identity, "read_only": True})
                return
            if request_path == "/api/architecture":
                try:
                    graph = load_architecture(milestone, root)
                except (ArchitectureError, OSError) as error:
                    self._json(422, {"error": str(error)})
                    return
                self._json(200, graph)
                return
            if request_path.startswith("/workspace/"):
                relative = unquote(request_path[len("/workspace/"):])
                target = (root / relative).resolve()
                try:
                    graph = load_architecture(milestone, root)
                    references = {root / "todo.md", milestone}
                    for module in graph["modules"]:
                        for category in ("code", "tests", "evidence"):
                            references.update((root / ref["path"]).resolve() for ref in module[category] if ref["exists"])
                    for step in graph["workflow_steps"]:
                        references.update((root / ref["path"]).resolve() for ref in step["evidence"] if ref["exists"])
                except (ArchitectureError, OSError):
                    self.send_error(404)
                    return
                if not target.is_relative_to(root) or target not in references or not target.is_file():
                    self.send_error(404)
                    return
                self._reply(200, target.read_bytes(), "text/plain; charset=utf-8")
                return
            filename = "index.html" if request_path == "/" else request_path.lstrip("/")
            if filename not in STATIC_TYPES:
                self.send_error(404)
                return
            asset = assets / filename
            if not asset.is_file():
                self.send_error(404)
                return
            self._reply(200, asset.read_bytes(), STATIC_TYPES[filename])

        def do_POST(self) -> None:
            """Input: local HTTP request. Output: rejection. Drain bounded bodies so Windows delivers the response."""
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                self.send_error(403, "Invalid local host")
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if 0 < size <= MAX_REJECT_BODY_BYTES and not self.headers.get("Transfer-Encoding"):
                    self.connection.settimeout(REJECT_BODY_TIMEOUT_SECONDS)
                    self.rfile.read(size)
            except (ValueError, OSError):
                pass
            self.send_error(405, "Viewer is read-only")

        def log_message(self, *_: object) -> None:
            return

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> int:
    """Input: CLI root/port. Output: exit code; serve the local viewer until stopped."""
    parser = argparse.ArgumentParser(description="Read-only project architecture viewer")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    with make_server(args.root, args.port) as server:
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

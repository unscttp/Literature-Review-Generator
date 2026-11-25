"""The local web app: a small JSON API and the static interface in ``web/``.

Standard library only (``http.server``). It listens on 127.0.0.1 and accepts
requests only for that host name and from its own pages: it checks the Host
header (against DNS rebinding) and the Origin of every change, and changes
must be sent as JSON (a form on another site cannot send JSON).
"""

from __future__ import annotations

import json
import mimetypes
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from . import ROOT, __version__
from .model import NoModel, local_settings, save_local_settings
from .pipeline import LANGUAGES, REVIEW_TYPES, SOURCES, RunError, RunService
from .references import STYLES

WEB = ROOT / "web"
MAX_BODY = 64 * 1024
RUN = r"/api/runs/(?P<run>[0-9A-Za-z-]+)"
ROUTES = [
    ("GET", r"/api/info", "info"),
    ("POST", r"/api/settings", "settings"),
    ("GET", r"/api/workflow", "workflow"),
    ("GET", r"/api/models", "models"),
    ("POST", r"/api/models/list", "model_list"),
    ("POST", r"/api/models/check", "model_check"),
    ("POST", r"/api/models/key", "model_key"),
    ("GET", r"/api/runs", "runs"),
    ("POST", r"/api/runs", "create"),
    ("GET", RUN, "run"),
    ("DELETE", RUN, "delete"),
    ("GET", RUN + r"/graph", "graph"),
    ("GET", RUN + r"/library", "library"),
    ("GET", RUN + r"/report", "report"),
    ("GET", RUN + r"/report\.md", "report_markdown"),
    ("GET", RUN + r"/references\.bib", "report_bibtex"),
    ("POST", RUN + r"/approvals/(?P<request>[0-9A-Za-z_-]+)", "decide"),
    ("POST", RUN + r"/cancel", "cancel"),
    ("POST", RUN + r"/resume", "resume"),
]


class ApiError(Exception):
    def __init__(self, status: int, message: str, code: str = "error") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class Api:
    """The API's handlers, independent of HTTP (the tests call them directly)."""

    def __init__(self, service: RunService) -> None:
        self.service = service

    def info(self, body, **_):
        return {
            "version": __version__,
            "demo": self.service.demo_label,
            "openalex_key": bool(local_settings().get("openalex_api_key")),
            "defaults": self.service.settings["defaults"],
            # Step limits per stage: base + per_paper * papers (see config/settings.json).
            "steps": {
                "base": {
                    node["id"]: node["react"]["max_steps"]
                    for node in self.service.workflow_document["nodes"]
                },
                "per_paper": self.service.settings.get("steps_per_paper", {}),
                "skill_graph": self.service.settings["engine"].get("graph_max_steps", 100),
            },
            "options": {
                "language": list(LANGUAGES),
                "style": list(STYLES),
                "review_type": list(REVIEW_TYPES),
                "sources": list(SOURCES),
            },
        }

    def settings(self, body, **_):
        if not isinstance(body, dict) or set(body) - {"openalex_api_key"}:
            raise ApiError(400, "Only openalex_api_key can be set here.")
        key = body.get("openalex_api_key")
        if key is not None and (not isinstance(key, str) or len(key) > 200):
            raise ApiError(400, "openalex_api_key must be a short string.")
        save_local_settings({"openalex_api_key": (key or "").strip()})
        return {"openalex_key": bool(local_settings().get("openalex_api_key"))}

    def workflow(self, body, **_):
        return self.service.workflow_view()

    # -- the model -------------------------------------------------------------
    # Keys go from the browser to this server and on to their service only; no
    # answer ever contains one (state() says only whether a key is saved).

    def models(self, body, **_):
        if self.service.demo_label:
            return {"demo": self.service.demo_label, "services": [], "current": None}
        return {"demo": None, **self.service.models.state()}

    @staticmethod
    def _fields(body, required, optional=()):
        if not isinstance(body, dict):
            raise ApiError(400, "Send a JSON object.")
        for name in (*required, *optional):
            value = body.get(name)
            if (name in required or value is not None) and not isinstance(value, str):
                raise ApiError(400, f"{name} must be a string.")
        return body

    def model_list(self, body, **_):
        body = self._fields(body, ["service"], ["base_url"])
        return self.service.models.models(body["service"], body.get("base_url"))

    def model_check(self, body, **_):
        body = self._fields(body, ["service", "model"], ["base_url"])
        problem = self.service.models.check(body)
        return {"ok": problem is None, "problem": problem}

    def model_key(self, body, **_):
        body = self._fields(body, ["service"], ["api_key"])
        self.service.models.save_key(body["service"], body.get("api_key"))
        return self.models(None)

    def runs(self, body, **_):
        return {"runs": self.service.list()}

    def create(self, body, **_):
        return self.service.create(body)

    def run(self, body, run):
        return self.service.summary(run)

    def delete(self, body, run):
        self.service.delete(run)
        return {"deleted": run}

    def graph(self, body, run):
        return self.service.graph(run)

    def library(self, body, run):
        return self.service.library(run)

    def report(self, body, run):
        return self.service.report(run)

    def report_markdown(self, body, run):
        return ("text/markdown; charset=utf-8", self.service.report(run)["markdown"], f"{run}.md")

    def report_bibtex(self, body, run):
        return (
            "application/x-bibtex; charset=utf-8",
            self.service.report(run)["bibtex"],
            f"{run}.bib",
        )

    def decide(self, body, run, request):
        if not isinstance(body, dict) or type(body.get("approved")) is not bool:
            raise ApiError(400, 'Send {"approved": true or false, "comment": "..."}.')
        comment = body.get("comment") or ""
        if not isinstance(comment, str):
            raise ApiError(400, "comment must be a string.")
        return self.service.decide(run, request, body["approved"], comment)

    def cancel(self, body, run):
        return self.service.cancel(run)

    def resume(self, body, run):
        return self.service.resume(run)

    def dispatch(self, method: str, path: str, body):
        for route_method, pattern, name in ROUTES:
            match = re.fullmatch(pattern, path)
            if match and route_method == method:
                try:
                    return getattr(self, name)(body, **match.groupdict())
                except KeyError:
                    raise ApiError(404, "No such review.", "not_found") from None
                except RunError as exc:
                    raise ApiError(400, str(exc), "invalid") from None
                except NoModel as exc:
                    raise ApiError(
                        400 if exc.code == "invalid" else 409, str(exc), exc.code
                    ) from None
        if any(re.fullmatch(pattern, path) for _, pattern, _ in ROUTES):
            raise ApiError(405, "Method not allowed.")
        raise ApiError(404, "Not found.", "not_found")


class Handler(BaseHTTPRequestHandler):
    api: Api
    allowed_hosts: set[str]
    server_version = f"LiteratureReviewGenerator/{__version__}"

    def log_message(self, format, *args):  # quiet: the terminal is for the user
        pass

    def _send(self, status: int, data: bytes, content_type: str, extra=None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'",
        )
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, status: int, value) -> None:
        self._send(
            status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json"
        )

    def _error(self, status: int, message: str, code: str = "error") -> None:
        self._json(status, {"error": message, "code": code})

    def _host_ok(self) -> bool:
        return (self.headers.get("Host") or "") in self.allowed_hosts

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or urlsplit(origin).netloc in self.allowed_hosts

    def _static(self, path: str) -> None:
        relative = "index.html" if path in ("", "/") else unquote(path).lstrip("/")
        target = (WEB / relative).resolve()
        if not target.is_relative_to(WEB.resolve()) or not target.is_file():
            return self._error(404, "Not found.", "not_found")
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if kind.startswith("text/") or kind in ("application/javascript", "application/json"):
            kind += "; charset=utf-8"
        self._send(200, target.read_bytes(), kind)

    def _handle(self, method: str) -> None:
        if not self._host_ok():
            return self._error(403, "Unknown host.")
        path = urlsplit(self.path).path
        if not path.startswith("/api/"):
            if method not in ("GET", "HEAD"):
                return self._error(405, "Method not allowed.")
            return self._static(path)
        body = None
        if method in ("POST", "DELETE"):
            if not self._origin_ok():
                return self._error(403, "Requests from other sites are refused.")
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._error(413, "Request too large.")
            raw = self.rfile.read(length) if length else b""
            if raw or method == "POST":
                if "application/json" not in (self.headers.get("Content-Type") or ""):
                    return self._error(415, "Send JSON.")
                try:
                    body = json.loads(raw or b"{}")
                except ValueError:
                    return self._error(400, "Invalid JSON.")
        try:
            result = self.api.dispatch(method, path, body)
        except ApiError as exc:
            return self._error(exc.status, str(exc), exc.code)
        except Exception as exc:  # a bug: say so instead of dropping the connection
            return self._error(500, f"{type(exc).__name__}: {exc}", "internal")
        if isinstance(result, tuple):  # a file download
            kind, text, filename = result
            return self._send(
                200,
                text.encode("utf-8"),
                kind,
                {"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        self._json(201 if method == "POST" and path == "/api/runs" else 200, result)

    def do_GET(self):
        self._handle("GET")

    def do_HEAD(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_DELETE(self):
        self._handle("DELETE")


def make_server(service: RunService, host: str = "127.0.0.1", port: int = 8765):
    handler = type("LrgHandler", (Handler,), {})
    handler.api = Api(service)
    server = ThreadingHTTPServer((host, port), handler)
    port = server.server_address[1]
    handler.allowed_hosts = {f"{host}:{port}", f"localhost:{port}", f"127.0.0.1:{port}"}
    server.daemon_threads = True
    return server


def serve_in_background(service: RunService, host="127.0.0.1", port=0):
    """Start the server in a thread (for tests); returns (server, base URL)."""
    server = make_server(service, host, port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://{host}:{server.server_address[1]}"

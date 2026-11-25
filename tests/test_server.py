"""The local web app over HTTP."""

import json
import urllib.error
import urllib.request

from tests.support import ServiceCase
from lrg.server import serve_in_background


class ServerTests(ServiceCase):
    def setUp(self):
        self.make_service()
        self.server, self.url = serve_in_background(self.service)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, path, method="GET", body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.url + path, data=data, method=method)
        if body is not None:
            request.add_header("Content-Type", "application/json")
        for name, value in (headers or {}).items():
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def json(self, *args, **kwargs):
        status, _, body = self.request(*args, **kwargs)
        return status, json.loads(body)

    def test_a_review_over_http(self):
        status, info = self.json("/api/info")
        self.assertEqual((status, info["demo"]), (200, None))
        self.assertIn("gbt7714", info["options"]["style"])
        status, error = self.json("/api/runs", "POST", {"topic": "x"})
        self.assertEqual((status, error["code"]), (400, "invalid"))
        status, run = self.json(
            "/api/runs", "POST", {"topic": "Irony in Austen", "language": "zh-CN"}
        )
        self.assertEqual(status, 201)
        summary = self.wait(run["id"])
        approval = summary["approvals"][0]["id"]
        status, error = self.json(
            f"/api/runs/{run['id']}/approvals/{approval}", "POST", {"approved": "yes"}
        )
        self.assertEqual(status, 400)
        status, _ = self.json(
            f"/api/runs/{run['id']}/approvals/{approval}", "POST", {"approved": True}
        )
        self.assertEqual(status, 200)
        self.wait(run["id"])
        status, graph = self.json(f"/api/runs/{run['id']}/graph")
        self.assertEqual(len(graph["graphs"][0]["nodes"]), 8)
        status, library = self.json(f"/api/runs/{run['id']}/library")
        self.assertEqual(library["counts"]["included"], 2)
        status, headers, body = self.request(f"/api/runs/{run['id']}/report.md")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn("## 参考文献", body.decode("utf-8"))
        status, runs = self.json("/api/runs")
        self.assertEqual([r["id"] for r in runs["runs"]], [run["id"]])
        status, _ = self.json(f"/api/runs/{run['id']}", "DELETE")
        self.assertEqual(status, 200)
        status, error = self.json(f"/api/runs/{run['id']}")
        self.assertEqual((status, error["code"]), (404, "not_found"))

    def test_workflow_and_static_files(self):
        status, view = self.json("/api/workflow")
        self.assertEqual(len(view["workflow"]["graphs"][0]["nodes"]), 8)
        self.assertEqual(len(view["skills"]), 4)
        self.assertTrue(all(len(skill["graphs"]) == 1 for skill in view["skills"]))
        status, headers, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(self.request("/i18n/zh-CN.json")[0], 200)
        self.assertEqual(self.request("/../lrg/server.py")[0], 404)
        self.assertEqual(self.request("/%2e%2e/config/settings.json")[0], 404)

    def test_other_sites_are_refused(self):
        status, _ = self.json("/api/info", headers={"Host": "evil.example:80"})
        self.assertEqual(status, 403)
        status, _ = self.json(
            "/api/runs", "POST", {"topic": "Irony"}, headers={"Origin": "http://evil.example"}
        )
        self.assertEqual(status, 403)
        request = urllib.request.Request(self.url + "/api/runs", data=b"topic=Irony", method="POST")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=10)
        self.assertEqual(caught.exception.code, 415)
        self.assertEqual(self.service.list(), [])

    def test_openalex_key_setting(self):
        from unittest.mock import patch

        import lrg.model

        with patch.object(lrg.model, "LOCAL_SETTINGS", self.service.data / "settings.json"):
            status, result = self.json("/api/settings", "POST", {"openalex_api_key": "abc"})
            self.assertEqual((status, result["openalex_key"]), (200, True))
            self.assertEqual(lrg.model.local_settings()["openalex_api_key"], "abc")
            status, result = self.json("/api/settings", "POST", {"openalex_api_key": ""})
            self.assertFalse(result["openalex_key"])
            status, _ = self.json("/api/settings", "POST", {"model": "x"})
            self.assertEqual(status, 400)

    def test_choosing_a_model_over_http(self):
        status, state = self.json("/api/models")
        self.assertEqual(state["current"], {"service": "openai", "model": "gpt-test"})
        self.assertNotIn("sk-test", json.dumps(state))
        status, reply = self.json("/api/models/list", "POST", {"service": "openai"})
        self.assertEqual(reply["models"], ["gpt-test", "gpt-other"])
        status, reply = self.json("/api/models/list", "POST", {"service": "claude"})
        self.assertEqual(reply["error"], "no_key")
        status, state = self.json(
            "/api/models/key", "POST", {"service": "claude", "api_key": "sk-ant"}
        )
        self.assertTrue(next(s for s in state["services"] if s["id"] == "claude")["has_key"])
        self.assertNotIn("sk-ant", json.dumps(state))
        status, reply = self.json("/api/models/check", "POST", {"service": "claude", "model": "c"})
        self.assertEqual((status, reply), (200, {"ok": True, "problem": None}))
        status, error = self.json("/api/models/check", "POST", {"service": "gemini", "model": "g"})
        self.assertEqual((status, error["code"]), (409, "no_key"))
        status, error = self.json("/api/models/list", "POST", {"service": 3})
        self.assertEqual(status, 400)
        status, run = self.json(
            "/api/runs", "POST", {"topic": "Irony", "model": {"service": "claude", "model": "c"}}
        )
        self.assertEqual((status, run["model"]), (201, "c · Anthropic"))
        status, error = self.json(
            "/api/runs", "POST", {"topic": "Irony", "model": {"service": "gemini", "model": "g"}}
        )
        self.assertEqual((status, error["code"]), (409, "no_key"))
        self.wait(run["id"])

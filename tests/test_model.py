"""Choosing the model: services, keys, model lists, the saved choice."""

import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from tests.support import ROOT  # noqa: F401
from lrg import model as model_module
from lrg.model import ModelStore, NoModel, fetch_models


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class ModelStoreTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "config.json"
        self.listed = []
        self.store = ModelStore(
            self.path,
            lister=lambda url, key: (
                self.listed.append((url, key)) or ["deepseek-v4-pro", "a-model", "z-model"]
            ),
            checker=lambda url, key, model, api: (
                None if model != "bad" else "HTTP 404: no such model"
            ),
        )
        patcher = patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("DGS_API_KEY", "DGS_MODEL", "DGS_BASE_URL"):
            os.environ.pop(name, None)

    def test_services_include_the_big_four(self):
        state = self.store.state()
        ids = [s["id"] for s in state["services"]]
        for service in ("gemini", "claude", "openai", "deepseek"):
            self.assertIn(service, ids)
        self.assertEqual(state["default_service"], "gemini")
        self.assertIsNone(state["current"])

    def test_keys_are_kept_per_service_and_never_shown(self):
        self.store.save_key("deepseek", "sk-deep")
        self.store.save_key("claude", "sk-ant")
        state = json.dumps(self.store.state())
        self.assertNotIn("sk-", state)
        has = {s["id"]: s["has_key"] for s in self.store.state()["services"]}
        self.assertTrue(has["deepseek"] and has["claude"] and not has["gemini"])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(NoModel):
            self.store.save_key("deepseek", "two words")
        self.store.save_key("claude", "")
        self.assertIsNone(self.store.key("claude"))

    def test_the_model_list_comes_from_the_service(self):
        reply = self.store.models("deepseek")
        self.assertEqual(reply["error"], "no_key")  # no key: not asked
        self.assertEqual(self.listed, [])
        self.store.save_key("deepseek", "sk-deep")
        reply = self.store.models("deepseek")
        self.assertEqual(self.listed, [("https://api.deepseek.com", "sk-deep")])
        self.assertEqual(
            reply["models"], ["deepseek-v4-pro", "z-model", "a-model"]
        )  # suggested first
        self.store.lister = lambda url, key: (_ for _ in ()).throw(
            RuntimeError("HTTP 401: bad key")
        )
        self.assertEqual(self.store.models("deepseek")["error"], "HTTP 401: bad key")
        # Local servers need no key; a custom API needs its base URL.
        self.store.lister = lambda url, key: ["llama4"]
        self.assertEqual(self.store.models("ollama")["models"], ["llama4"])
        self.assertTrue(self.store.models("custom")["error"])
        self.assertEqual(
            self.store.models("custom", "https://llm.example/v1")["models"], ["llama4"]
        )
        with self.assertRaises(NoModel):
            self.store.models("custom", "file:///etc")

    def test_choices(self):
        with self.assertRaises(NoModel) as caught:
            self.store.clean({"service": "claude", "model": "claude-opus-5-5"})
        self.assertEqual(caught.exception.code, "no_key")
        self.store.save_key("claude", "sk-ant")
        choice = self.store.clean(
            {"service": "claude", "model": " claude-opus-5-5 ", "base_url": None}
        )
        self.assertEqual(choice, {"service": "claude", "model": "claude-opus-5-5"})
        self.store.save_choice(choice)
        self.assertEqual(self.store.current(), choice)
        saved = json.loads(self.path.read_text())
        self.assertEqual(
            (saved["model"], saved["api_key"]), ("claude-opus-5-5", "sk-ant")
        )  # DGS format
        self.assertEqual(self.store.label(choice), "claude-opus-5-5 · Anthropic")
        custom = self.store.clean(
            {"service": "custom", "model": "m", "base_url": "https://llm.example/v1/"}
        )
        self.assertEqual(custom["base_url"], "https://llm.example/v1")
        self.store.save_choice(custom)
        self.assertEqual(self.store.current(), custom)
        self.assertIsNone(self.store.check(custom))
        self.assertIn("404", self.store.check({**custom, "model": "bad"}))
        for bad in (None, {}, {"service": "claude"}, {"service": "claude", "model": ""}):
            with self.assertRaises(NoModel):
                self.store.clean(bad)

    def test_adapters(self):
        self.store.save_key("openai", "sk-oa")
        self.store.save_key("gemini", "g-key")
        with patch.object(model_module, "openai_responses", return_value="responses") as responses:
            self.assertEqual(
                self.store.adapter({"service": "openai", "model": "gpt-6.2-astra"}), "responses"
            )
        responses.assert_called_once_with("gpt-6.2-astra", "sk-oa", "https://api.openai.com/v1")
        with patch.object(model_module, "openai_compatible", return_value="chat") as chat:
            self.store.adapter({"service": "gemini", "model": "gemini-4-hydrogen"})
        chat.assert_called_once_with(
            "gemini-4-hydrogen", "g-key", "https://generativelanguage.googleapis.com/v1beta/openai"
        )

    def test_a_choice_saved_by_the_terminal_setup(self):
        self.path.write_text(
            json.dumps(
                {
                    "service": "deepseek",
                    "label": "DeepSeek V4 Pro",
                    "base_url": "https://api.deepseek.com",
                    "model": "deepseek-v4-pro",
                    "api": "chat",
                    "api_key": "sk-old",
                }
            )
        )
        self.assertEqual(self.store.key("deepseek"), "sk-old")
        self.assertEqual(self.store.current(), {"service": "deepseek", "model": "deepseek-v4-pro"})

    def test_terminal_setup_keeps_the_other_keys(self):
        self.store.save_key("claude", "sk-ant")

        def setup_model(path, services_path):
            Path(path).write_text(
                json.dumps(
                    {
                        "service": "gemini",
                        "model": "gemini-4-hydrogen",
                        "base_url": "x",
                        "api": "chat",
                        "api_key": "g-new",
                    }
                )
            )
            return {"service": "gemini"}

        with patch("workflow_model_setup.setup_model", setup_model):
            self.store.terminal_setup()
        self.assertEqual((self.store.key("claude"), self.store.key("gemini")), ("sk-ant", "g-new"))
        self.assertEqual(self.store.current()["service"], "gemini")

    def test_environment_overrides(self):
        self.store.save_key("deepseek", "sk-file")
        self.store.save_choice({"service": "deepseek", "model": "deepseek-v4-pro"})
        with patch.dict(os.environ, {"DGS_API_KEY": "sk-env", "DGS_MODEL": "deepseek-flash"}):
            self.assertEqual(self.store.key("deepseek"), "sk-env")
            self.assertIsNone(self.store.key("claude"))
            self.assertEqual(self.store.current()["model"], "deepseek-flash")


class FetchModelsTests(unittest.TestCase):
    def test_list_and_filter(self):
        body = {
            "data": [
                {"id": "models/gemini-4-hydrogen"},
                {"id": "text-embedding-005"},
                {"id": "gpt-image-2"},
                {"id": "whisper-2"},
                {"id": "claude-opus-5-5"},
            ]
        }
        with patch(
            "urllib.request.urlopen", return_value=Response(json.dumps(body).encode())
        ) as urlopen:
            models = fetch_models("https://api.anthropic.com/v1/", "sk-ant")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.anthropic.com/v1/models")
        self.assertEqual(request.get_header("Authorization"), "Bearer sk-ant")
        self.assertEqual(request.get_header("X-api-key"), "sk-ant")
        self.assertEqual(models, ["claude-opus-5-5", "gemini-4-hydrogen"])
        with patch("urllib.request.urlopen", return_value=Response(b'{"data": []}')) as urlopen:
            fetch_models("https://api.deepseek.com", "sk")
        self.assertIsNone(urlopen.call_args.args[0].get_header("X-api-key"))

    def test_errors_hide_the_key(self):
        error = urllib.error.HTTPError(
            "u", 401, "no", {}, io.BytesIO(b'{"error": {"message": "bad key sk-x"}}')
        )
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(RuntimeError) as caught:
                fetch_models("https://api.openai.com/v1", "sk-x")
        self.assertEqual(str(caught.exception), "HTTP 401: bad key [key]")


if __name__ == "__main__":
    unittest.main()

"""Helpers for the tests: the demo script and fake sources run the whole workflow offline."""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import lrg  # noqa: E402,F401  (puts DGS on the path)
from lrg.demo import ScriptedModel, demo_arxiv, demo_openalex, demo_script  # noqa: E402


CHOICE = {"service": "openai", "model": "gpt-test"}
LABEL = "gpt-test · OpenAI"


def model_store(folder: Path, *, lister=None, checker=None, choice=CHOICE, key="sk-test"):
    """A model store in a temporary folder with a saved choice and key."""
    from lrg.model import ModelStore

    store = ModelStore(
        Path(folder) / "model-config.json",
        lister=lister or (lambda url, key: ["gpt-other", "gpt-test"]),
        checker=checker or (lambda url, key, model, api: None),
    )
    if key:
        store.save_key(choice["service"], key)
    if choice:
        store.save_choice(choice)
    return store


class ServiceCase(unittest.TestCase):
    def make_service(self, script=None, **kwargs):
        from lrg.pipeline import RunService

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.model = ScriptedModel(script or demo_script())
        self.chosen = []  # the choices the service built models for
        options = dict(
            models=model_store(Path(folder.name)),
            model_factory=lambda choice: self.chosen.append(choice) or self.model,
            openalex=demo_openalex,
            arxiv=demo_arxiv,
        )
        options.update(kwargs)
        self.service = RunService(Path(folder.name), **options)
        return self.service

    def wait(self, run_id, statuses=("waiting", "completed", "failed", "cancelled"), timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            summary = self.service.summary(run_id)
            state = self.service._states.get(run_id)
            if summary["status"] in statuses and (state is None or state.thread is None):
                return summary
            time.sleep(0.02)
        raise AssertionError(f"run still {self.service.summary(run_id)['status']}")

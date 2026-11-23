"""The model the stages use, and the local settings file.

``python install.py`` (or ``python run.py --setup``) asks which model to use
with DGS's own setup (``workflow_model_setup``): Gemini 4 Hydrogen by default,
Claude, GPT, DeepSeek, a local Ollama or LM Studio, or any OpenAI-compatible
API. The choice is saved in ``.lrg/config.json`` (readable only by you). The
stages talk to the model through DGS's adapters: ``openai_responses`` for
OpenAI's newest models, ``openai_compatible`` for everything else.

Other local settings (the OpenAlex key) live in ``.lrg/settings.json``.
Environment variables override both: ``DGS_API_KEY``, ``DGS_MODEL``,
``DGS_BASE_URL`` and ``LRG_OPENALEX_API_KEY``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

from workflow_core import openai_compatible, openai_responses
from workflow_model_setup import load_config, save_config

from . import ROOT

LOCAL = ROOT / ".lrg"
MODEL_CONFIG = LOCAL / "config.json"
LOCAL_SETTINGS = LOCAL / "settings.json"


class NoModel(RuntimeError):
    """No model has been chosen yet."""


def model_config(path: Path | None = None) -> dict:
    return load_config(path or MODEL_CONFIG)


def model_label(config: dict | None = None) -> str | None:
    config = model_config() if config is None else config
    if not config.get("model"):
        return None
    label = config.get("label")
    return f"{config['model']} ({label})" if label else config["model"]


def create_model(config: dict | None = None) -> Callable:
    """The DGS model adapter for the saved choice."""
    config = model_config() if config is None else config
    if not config.get("model") or not config.get("base_url"):
        raise NoModel("No model chosen yet: run python run.py --setup")
    if config.get("api") == "responses":
        return openai_responses(config["model"], config.get("api_key"), config["base_url"])
    return openai_compatible(config["model"], config.get("api_key"), config["base_url"])


def with_rules(adapter: Callable, rules: str, cancelled: Callable[[], bool] = lambda: False):
    """Give every node the review's rules (appended to DGS's system prompt), and
    stop a cancelled run before its next model call."""

    def model(messages):
        if cancelled():
            raise RunCancelled("The run was cancelled.")
        system = {**messages[0], "content": messages[0]["content"] + "\n\n" + rules}
        return adapter([system, *messages[1:]])

    return model


class RunCancelled(RuntimeError):
    pass


def local_settings(path: Path | None = None) -> dict:
    try:
        settings = json.loads((path or LOCAL_SETTINGS).read_text("utf-8"))
    except (OSError, ValueError):
        settings = {}
    if os.environ.get("LRG_OPENALEX_API_KEY"):
        settings["openalex_api_key"] = os.environ["LRG_OPENALEX_API_KEY"]
    return settings


def save_local_settings(changes: dict, path: Path | None = None) -> dict:
    path = path or LOCAL_SETTINGS
    try:
        settings = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        settings = {}
    for key, value in changes.items():
        if value in (None, ""):
            settings.pop(key, None)
        else:
            settings[key] = value
    save_config(settings, path)  # same as the model config: mode 600
    return settings

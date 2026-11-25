"""The AI model the stages use: services, keys, model lists and the saved choice.

The services are listed in ``config/models.json`` (Gemini, Claude, GPT,
DeepSeek, Ollama and LM Studio on this computer, any OpenAI-compatible API).
The user chooses a service and a model in the web interface; the list of
models comes from the service itself (``GET <base_url>/models`` with the
user's key), so new models appear without updating the app.

Keys are saved per service in ``.lrg/config.json``, readable only by the user,
and never sent back to the browser. Each review records the service and model
it uses (never the key); the key is looked up when the review runs. The file
keeps DGS's format for the current choice (``service``, ``model``,
``base_url``, ``api``, ``api_key``), so ``python run.py --setup`` (DGS's
terminal setup) still works, and the environment variables ``DGS_API_KEY``,
``DGS_MODEL`` and ``DGS_BASE_URL`` still override it.

The stages talk to the model through DGS's adapters: ``openai_responses`` for
OpenAI's newest models, ``openai_compatible`` for everything else.
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from workflow_core import openai_compatible, openai_responses
from workflow_model_setup import CHECK_PROMPT, Service, load_services, save_config

from . import ROOT

LOCAL = ROOT / ".lrg"
MODEL_CONFIG = LOCAL / "config.json"
LOCAL_SETTINGS = LOCAL / "settings.json"
SERVICES = ROOT / "config" / "models.json"
TIMEOUT_SECONDS = 20
# Models a /models endpoint lists that cannot hold a conversation with tools.
NOT_CHAT = re.compile(
    r"embed|tts|whisper|dall-e|davinci|babbage|imagen|veo|image|audio|transcri|"
    r"moderation|realtime|aqa|rerank",
    re.IGNORECASE,
)


class NoModel(RuntimeError):
    """No usable model: none chosen, unknown service or no key."""

    def __init__(self, message: str, code: str = "no_model") -> None:
        super().__init__(message)
        self.code = code


def _message(body: str) -> str:
    """The provider's own error message, on one line."""
    try:
        data = json.loads(body)
    except ValueError:
        return " ".join(body.split())[:200]
    if isinstance(data, list) and data:
        data = data[0]
    error = data.get("error", data) if isinstance(data, dict) else data
    if isinstance(error, dict):
        error = error.get("message") or error
    return str(error)[:200]


def _request(url: str, key: str | None, body: dict | None = None, timeout=TIMEOUT_SECONDS):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
        if "api.anthropic.com" in url:  # Anthropic's own endpoints read these
            headers["x-api-key"] = key
            headers["anthropic-version"] = "2023-06-01"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url, data=data, headers=headers, method="POST" if body is not None else "GET"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        text = _message(exc.read().decode("utf-8", "replace"))
        if key:
            text = text.replace(key, "[key]")
        raise RuntimeError(f"HTTP {exc.code}: {text}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Could not connect ({getattr(exc, 'reason', exc)}).") from None
    except ValueError:
        raise RuntimeError("The service did not answer with JSON.") from None


def fetch_models(base_url: str, key: str | None) -> list[str]:
    """Model IDs the key can use, as the service reports them."""
    data = _request(base_url.rstrip("/") + "/models", key)
    items = data.get("data") if isinstance(data, dict) else None
    if items is None and isinstance(data, dict):
        items = data.get("models")  # some local servers
    ids = {
        str(item.get("id") or item.get("name") or "").removeprefix("models/")
        for item in items or []
        if isinstance(item, dict)
    }
    return sorted(i for i in ids if i and not NOT_CHAT.search(i))


def check_model(base_url: str, key: str | None, model: str, api: str = "chat") -> str | None:
    """One tiny request: None if it worked, otherwise why not."""
    try:
        if api == "responses":
            body = {"model": model, "input": CHECK_PROMPT, "store": False}
            _request(base_url.rstrip("/") + "/responses", key, body, timeout=60)["output"]
        else:
            body = {"model": model, "messages": [{"role": "user", "content": CHECK_PROMPT}]}
            reply = _request(base_url.rstrip("/") + "/chat/completions", key, body, timeout=60)
            reply["choices"][0]["message"]
    except (RuntimeError, KeyError, IndexError, TypeError) as exc:
        return str(exc) if isinstance(exc, RuntimeError) else "Unexpected answer from the service."
    return None


class ModelStore:
    """The services, the saved keys and the current choice."""

    def __init__(
        self,
        path: Path | None = None,
        services_path: Path | None = None,
        *,
        lister: Callable[[str, str | None], list[str]] = fetch_models,
        checker: Callable[..., str | None] = check_model,
    ) -> None:
        self.path = Path(path or MODEL_CONFIG)
        self.services_path = Path(services_path or SERVICES)
        self.lister = lister
        self.checker = checker
        self._lock = threading.Lock()

    # -- the file ----------------------------------------------------------------

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        keys = data.setdefault("keys", {})
        base_urls = data.setdefault("base_urls", {})
        # A choice saved by DGS's terminal setup has only api_key and base_url:
        # file them under its service.
        service = data.get("service")
        if service and data.get("api_key") and service not in keys:
            keys[service] = data["api_key"]
        if service and data.get("base_url") and service not in base_urls:
            base_urls[service] = data["base_url"]
        return data

    def _write(self, data: dict) -> None:
        current = data.get("service")
        data["api_key"] = data.get("keys", {}).get(current) if current else None
        if not data["api_key"]:
            data.pop("api_key")
        save_config(data, self.path)  # mode 600: it holds keys

    # -- services ----------------------------------------------------------------

    def services(self) -> tuple[list[Service], str]:
        services, default = load_services(self.services_path)
        return services, services[default].id

    def service(self, service_id: str) -> Service:
        services, _ = self.services()
        for service in services:
            if service.id == service_id:
                return service
        raise NoModel(f"Unknown service {service_id!r}.", "invalid")

    def key(self, service_id: str) -> str | None:
        data = self._read()
        if os.environ.get("DGS_API_KEY") and data.get("service", service_id) == service_id:
            return os.environ["DGS_API_KEY"]
        return data["keys"].get(service_id)

    def base_url(self, service: Service, given: str | None = None) -> str | None:
        url = (given or "").strip() or service.base_url
        if not url:
            url = self._read().get("base_urls", {}).get(service.id)
        if (
            os.environ.get("DGS_BASE_URL")
            and self._read().get("service") == service.id
            and not given
        ):
            url = os.environ["DGS_BASE_URL"]
        if url and not re.match(r"^https?://[^\s]+$", url):
            raise NoModel("The base URL must start with http:// or https://.", "invalid")
        return url.rstrip("/") if url else None

    def state(self) -> dict:
        """What the interface shows: services, which have keys, the current choice."""
        services, default = self.services()
        data = self._read()
        return {
            "services": [
                {
                    "id": s.id,
                    "label": s.label,
                    "needs_key": s.needs_key,
                    "key_hint": s.key_hint,
                    "has_key": bool(self.key(s.id)),
                    "suggested_model": s.model,
                    "base_url": s.base_url or data["base_urls"].get(s.id),
                    "fixed_base_url": s.base_url is not None,
                }
                for s in services
            ],
            "default_service": default,
            "current": self.current(),
        }

    def current(self) -> dict | None:
        data = self._read()
        if os.environ.get("DGS_MODEL"):
            data["model"] = os.environ["DGS_MODEL"]
        if not data.get("service") or not data.get("model"):
            return None
        choice = {"service": data["service"], "model": data["model"]}
        try:
            fixed = self.service(data["service"]).base_url
        except NoModel:
            return None  # a service no longer offered
        if not fixed and data["base_urls"].get(data["service"]):
            choice["base_url"] = data["base_urls"][data["service"]]
        return choice

    # -- changing -----------------------------------------------------------------

    def save_key(self, service_id: str, key: str | None) -> None:
        self.service(service_id)
        key = (key or "").strip()
        if len(key) > 500 or any(c.isspace() for c in key):
            raise NoModel("That does not look like an API key.", "invalid")
        with self._lock:
            data = self._read()
            if key:
                data["keys"][service_id] = key
            else:
                data["keys"].pop(service_id, None)
            self._write(data)

    def save_choice(self, choice: dict) -> None:
        service, base_url, _ = self.resolve(choice, need_key=False)
        with self._lock:
            data = self._read()
            data.update(
                service=service.id,
                label=service.label,
                model=choice["model"],
                base_url=base_url,
                api=service.api,
            )
            data["base_urls"][service.id] = base_url
            self._write(data)

    def terminal_setup(self) -> dict | None:
        """DGS's terminal setup (``python run.py --setup``), keeping the other saved keys."""
        from workflow_model_setup import setup_model

        previous = self._read()
        result = setup_model(path=self.path, services_path=self.services_path)
        with self._lock:
            data = self._read()  # setup_model rewrote the file with this choice only
            keys = {**previous["keys"], **data["keys"]}
            base_urls = {**previous["base_urls"], **data["base_urls"]}
            data.update(keys=keys if result else previous["keys"], base_urls=base_urls)
            if not result:  # cancelled: put the previous choice back
                data = previous
            self._write(data)
        return result

    # -- using a choice ------------------------------------------------------------

    def resolve(self, choice: dict | None, *, need_key: bool = True):
        """(service, base URL, key) for a choice; NoModel says what is missing."""
        if not isinstance(choice, dict) or not choice.get("service"):
            raise NoModel("Choose a model first.")
        service = self.service(choice["service"])
        model = choice.get("model")
        if not isinstance(model, str) or not model.strip() or len(model) > 200:
            raise NoModel("Choose a model first.")
        base_url = self.base_url(service, choice.get("base_url"))
        if not base_url:
            raise NoModel("Enter the base URL of the API.", "invalid")
        key = self.key(service.id)
        if need_key and service.needs_key and service.base_url and not key:
            raise NoModel(f"No API key saved for {service.label}.", "no_key")
        return service, base_url, key

    def clean(self, choice: dict) -> dict:
        """The choice as a review records it: no key."""
        service, base_url, _ = self.resolve(choice)
        cleaned = {"service": service.id, "model": choice["model"].strip()}
        if not service.base_url:
            cleaned["base_url"] = base_url
        return cleaned

    def label(self, choice: dict) -> str:
        try:
            service = self.service(choice["service"])
        except NoModel:
            return choice.get("model", "?")
        name = service.label.split(" (")[-1].rstrip(")") if "(" in service.label else service.label
        return f"{choice['model']} · {name}"

    def adapter(self, choice: dict) -> Callable:
        """The DGS model adapter for a choice."""
        service, base_url, key = self.resolve(choice)
        if service.api == "responses":
            return openai_responses(choice["model"], key, base_url)
        return openai_compatible(choice["model"], key, base_url)

    def models(self, service_id: str, base_url: str | None = None) -> dict:
        """The models the service offers this key, suggested model first."""
        service = self.service(service_id)
        url = self.base_url(service, base_url)
        reply = {"service": service.id, "suggested": service.model, "models": [], "error": None}
        if not url:
            reply["error"] = "Enter the base URL of the API."
            return reply
        key = self.key(service.id)
        if service.needs_key and service.base_url and not key:
            reply["error"] = "no_key"
            return reply
        try:
            models = self.lister(url, key)
        except Exception as exc:
            reply["error"] = str(exc)
            return reply
        suggested = [m for m in models if m == service.model]
        reply["models"] = suggested + sorted(
            (m for m in models if m != service.model), reverse=True
        )
        return reply

    def check(self, choice: dict) -> str | None:
        service, base_url, key = self.resolve(choice)
        return self.checker(base_url, key, choice["model"].strip(), service.api)


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

"""Start the Literature Review Generator: python run.py

Opens the app in your browser (http://127.0.0.1:8765). Stop it with Ctrl+C.

  python run.py --setup      choose the AI model (also asked by install.py)
  python run.py --demo       try the app with a scripted demo, no AI and no key
  python run.py --port 9000  use another port
  python run.py --no-browser do not open the browser
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def in_venv() -> bool:
    return Path(sys.prefix).resolve() == VENV.resolve()


def main(argv=None) -> int:
    # Use the environment install.py made, without asking the user to activate it.
    if venv_python().exists() and not in_venv() and not os.environ.get("LRG_NO_VENV"):
        return subprocess.call([str(venv_python()), str(Path(__file__)), *(argv or sys.argv[1:])])

    parser = argparse.ArgumentParser(description="Literature Review Generator")
    parser.add_argument("--setup", action="store_true", help="choose the AI model")
    parser.add_argument(
        "--demo", action="store_true", help="scripted demo: no AI, no key, no network"
    )
    parser.add_argument("--port", type=int, help="port (default from config/settings.json)")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(ROOT))
    try:
        import lrg  # noqa: F401  (finds Directed Growing Sheet)
    except ImportError as exc:
        print(exc)
        return 1
    from lrg.model import MODEL_CONFIG, model_label

    if args.setup:
        from workflow_model_setup import setup_model

        return 0 if setup_model(path=MODEL_CONFIG) else 1

    from lrg.pipeline import RunService, load_settings
    from lrg.server import make_server

    settings = load_settings()
    options = {}
    if args.demo:
        from lrg.demo import MODEL_LABEL, ScriptedModel, demo_arxiv, demo_openalex

        options = dict(
            data_dir=ROOT / "data" / "demo",
            model_factory=lambda: ScriptedModel(delay=0.6),
            model_name=lambda: MODEL_LABEL,
            openalex=demo_openalex,
            arxiv=demo_arxiv,
        )
    elif not model_label():
        if sys.stdin.isatty():
            print("No model chosen yet.")
            from workflow_model_setup import setup_model

            setup_model(path=MODEL_CONFIG)
        else:
            print("No model chosen yet: run python run.py --setup")

    service = RunService(settings=settings, **options)
    host = settings.get("host", "127.0.0.1")
    port = args.port or settings.get("port", 8765)
    try:
        server = make_server(service, host, port)
    except OSError as exc:
        print(f"Cannot use port {port} ({exc.strerror}). Try: python run.py --port {port + 1}")
        return 1
    url = f"http://{host}:{server.server_address[1]}/"
    print(f"Literature Review Generator{' (demo)' if args.demo else ''} is running at {url}")
    print("Keep this window open while you use it; press Ctrl+C to stop.")
    if not args.no_browser:
        import webbrowser

        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

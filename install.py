"""One-step setup: python install.py

1. Fetches Directed Growing Sheet (DGS), the workflow engine, into
   third_party/dgs if it is not there yet (git submodule, or a download when
   the folder came from a ZIP).
2. Creates a private Python environment in .venv and installs the one
   dependency (PyYAML, for Agent Skills).
3. Runs the tests: a complete scripted review, no AI and no key needed.

Then start the app (python run.py) and choose the AI model in it. Run this
again at any time; it only adds what is missing.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import urllib.request
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
DGS = ROOT / "third_party" / "dgs"
# The DGS version this app is tested with (the submodule's commit).
DGS_REPOSITORY = "https://github.com/unscttp/Directed-Growing-Sheet"
DGS_COMMIT = "2253b48f569d95b12daa91678376d03b2f28a292"


def python_in_venv() -> Path:
    return VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def run(*command, check=True) -> int:
    print("$", " ".join(str(part) for part in command))
    return subprocess.run([str(part) for part in command], cwd=ROOT, check=check).returncode


def fetch_dgs() -> None:
    if (DGS / "workflow_core.py").is_file():
        return
    if (ROOT / ".git").exists() and shutil.which("git"):
        print("Fetching Directed Growing Sheet (git submodule) ...")
        if run("git", "submodule", "update", "--init", "--recursive", check=False) == 0:
            if (DGS / "workflow_core.py").is_file():
                return
    print("Downloading Directed Growing Sheet ...")
    url = f"{DGS_REPOSITORY}/archive/{DGS_COMMIT}.zip"
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            archive = zipfile.ZipFile(io.BytesIO(response.read()))
    except Exception as exc:
        sys.exit(
            f"Could not download {url} ({exc}).\n"
            "Clone the app with git instead:\n"
            "  git clone --recursive https://github.com/unscttp/Literature-Review-Generator"
        )
    prefix = archive.namelist()[0].split("/")[0] + "/"
    DGS.mkdir(parents=True, exist_ok=True)
    for member in archive.infolist():
        name = member.filename.removeprefix(prefix)
        target = (DGS / name).resolve()
        if not name or not target.is_relative_to(DGS.resolve()):
            continue
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(member))


def main() -> int:
    if sys.version_info < (3, 10):  # noqa: UP036 (install.py may be run by an old Python)
        print("Python 3.10 or later is needed; this is", sys.version.split()[0])
        return 1
    fetch_dgs()
    if not python_in_venv().exists():
        print("Creating the Python environment in .venv ...")
        venv.EnvBuilder(with_pip=True).create(VENV)
    python = python_in_venv()
    run(python, "-m", "pip", "install", "--quiet", "--upgrade", "pip")
    run(python, "-m", "pip", "install", "--quiet", "-r", "requirements.txt")
    print("\nSelf-check (a scripted review, no AI and no key needed):")
    run(python, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-q")
    print(
        "\nDone. Start the app with:\n"
        "  python run.py\n"
        "and choose the AI model and enter its API key on the new-review page,\n"
        "or try it first without an AI model:\n"
        "  python run.py --demo\n"
        "See README.md for details."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

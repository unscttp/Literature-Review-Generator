"""Literature Review Generator: an eight-stage literature review workflow on DGS.

Directed Growing Sheet (DGS) is included as a git submodule in
``third_party/dgs``; importing this package puts it on ``sys.path`` unless DGS
is installed already.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DGS = ROOT / "third_party" / "dgs"

try:
    import workflow_core  # noqa: F401  (an installed DGS)
except ImportError:
    if not (DGS / "workflow_core.py").is_file():
        raise ImportError(
            "Directed Growing Sheet is missing from third_party/dgs. Run: python install.py"
        ) from None
    sys.path.insert(0, str(DGS))

__version__ = "1.4.1"

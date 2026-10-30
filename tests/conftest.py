from __future__ import annotations

import sys
from pathlib import Path


PYTHON_ROOT = Path(__file__).resolve().parents[1] / "app" / "src" / "main" / "python"
sys.path.insert(0, str(PYTHON_ROOT))

from pydantic_v1_compat import install as install_pydantic_v1_compat

install_pydantic_v1_compat()

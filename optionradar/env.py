"""Minimal .env loader (no third-party dependency).

Reads KEY=VALUE lines from a .env file in the project root and sets them in
os.environ if not already set. Comments (#) and blank lines are ignored. This
lets local runs pick up secrets without exporting them by hand; in GitHub
Actions the secrets are already in the environment so this is a no-op.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ENV = Path(__file__).resolve().parent.parent / ".env"


def load_dotenv(path: str | Path = DEFAULT_ENV, override: bool = False) -> int:
    path = Path(path)
    if not path.exists():
        return 0
    loaded = 0
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded

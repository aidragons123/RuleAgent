"""platform/config.py (on disk: ai_platform/config.py). PRE-BUILT."""
from __future__ import annotations

import functools
from pathlib import Path

import yaml

_HERE = Path(__file__).parent


@functools.lru_cache(maxsize=1)
def get_config() -> dict:
    with open(_HERE / "config.yaml") as f:
        return yaml.safe_load(f)

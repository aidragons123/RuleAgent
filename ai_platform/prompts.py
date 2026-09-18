"""
platform/prompts.py (on disk: ai_platform/prompts.py). PRE-BUILT.

Loads ai/prompts/*.md and does simple {{var}} substitution. Prompts
live as files, on purpose: inline prompt strings written in Python are
not reviewable in a diff the same way, and this loader is the only
sanctioned way an AILayer gets prompt text.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "ai" / "prompts"

_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


class PromptLoader:
    def __init__(self, prompts_dir: Path = _PROMPTS_DIR):
        self.prompts_dir = prompts_dir
        self._cache: dict[str, str] = {}

    def _load(self, name: str) -> str:
        if name not in self._cache:
            path = self.prompts_dir / f"{name}.md"
            if not path.exists():
                raise FileNotFoundError(
                    f"No prompt file ai/prompts/{name}.md - inline prompts are rejected."
                )
            self._cache[name] = path.read_text()
        return self._cache[name]

    def render(self, name: str, ctx: dict) -> str:
        template = self._load(name)

        def _sub(m: re.Match) -> str:
            key = m.group(1)
            val = ctx
            for part in key.split("."):
                if isinstance(val, dict) and part in val:
                    val = val[part]
                else:
                    return m.group(0)
            if not isinstance(val, str):
                val = json.dumps(val, default=str, indent=2)
            return val

        return _VAR_RE.sub(_sub, template)

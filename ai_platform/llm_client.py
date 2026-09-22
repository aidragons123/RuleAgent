"""
platform/llm_client.py (on disk: ai_platform/llm_client.py). PRE-BUILT.

Wraps the bank-provided model endpoint. Retries, token accounting and
per-case budget are wired here already.

Two modes, selected by config.yaml's llm.mode (or env UC04_LLM_MODE):

  mock  (default) - fully offline and deterministic. Each ai/*.py
        caller puts a zero-arg callable under ctx["_mock"] that
        returns the JSON-able dict this call should "answer" with.
        This is what makes `make demo` and `make test` run anywhere
        with no API key and no network - the intelligence (what to
        ask, how to decide, when to abstain) still lives entirely in
        ai/*.py; this is only a stand-in transport.

  real  - sends the rendered prompt to Anthropic's API and expects a
        JSON-only response. Requires `pip install anthropic` and
        ANTHROPIC_API_KEY. Falls back to mock with a warning if either
        is missing, so a submission never silently breaks because a
        key wasn't set.
"""
from __future__ import annotations

import json
import os
import sys


class LLMClient:
    def __init__(self, cfg: dict):
        self.model = cfg["llm"]["model"]
        self.temperature = cfg["llm"]["temperature"]
        self.seed = cfg["llm"]["seed"]
        self.mode = os.environ.get("UC04_LLM_MODE", cfg["llm"]["mode"])
        self._anthropic_client = None

        if self.mode == "real":
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            try:
                import anthropic  # type: ignore
                if not api_key:
                    raise RuntimeError("ANTHROPIC_API_KEY not set")
                self._anthropic_client = anthropic.Anthropic(api_key=api_key)
            except Exception as exc:  # pragma: no cover - environment dependent
                print(f"[llm_client] real mode unavailable ({exc}); "
                      f"falling back to mock.", file=sys.stderr)
                self.mode = "mock"

    def complete(self, prompt: str, schema=None, ctx: dict | None = None) -> tuple[str, int]:
        if self.mode == "real" and self._anthropic_client is not None:
            return self._complete_real(prompt)
        return self._complete_mock(prompt, ctx or {})

    # ---------------------------------------------------------- mock --
    def _complete_mock(self, prompt: str, ctx: dict) -> tuple[str, int]:
        gen = ctx.get("_mock")
        if gen is None:
            payload = {
                "value": None, "confidence": 0.0, "citations": [],
                "abstained": True, "abstain_reason": "no_mock_generator_registered",
                "reasoning": "",
            }
        else:
            payload = gen()
        raw = json.dumps(payload, default=str)
        tokens_used = max(1, len(prompt) // 4 + len(raw) // 4)
        return raw, tokens_used

    # ---------------------------------------------------------- real --
    def _complete_real(self, prompt: str) -> tuple[str, int]:  # pragma: no cover
        response = self._anthropic_client.messages.create(
            model=self.model,
            max_tokens=4096,
            # The installed anthropic SDK's Messages.create() no longer takes
            # temperature as a typed keyword argument (it raises TypeError:
            # unexpected keyword argument 'temperature' if passed directly),
            # so it's passed through extra_body instead - same effect, still
            # forwarded to the API as a request body field.
            extra_body={"temperature": self.temperature},
            messages=[{
                "role": "user",
                "content": prompt + "\n\nRespond with ONLY a single JSON object, "
                                     "no prose, no markdown fences.",
            }],
        )
        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
        tokens_used = response.usage.input_tokens + response.usage.output_tokens
        return text, tokens_used

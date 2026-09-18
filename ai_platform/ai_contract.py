"""
platform/ai_contract.py  (on disk: ai_platform/ai_contract.py — see the
README note on the platform/ folder name.) PRE-BUILT. Do not edit.

Every AI method you implement in ai/ returns the same envelope,
defined once here. The platform enforces the 8 rules in the table
below on every call through AILayer.call(); you get correct behaviour
without writing any of this yourself.
"""
from __future__ import annotations

import functools
import time
from abc import ABC
from typing import Generic, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from .config import get_config
from .guardrails import GuardrailViolation, check_no_equivalence_claim
from .llm_client import LLMClient
from .prompts import PromptLoader

T = TypeVar("T")


class Citation(BaseModel):
    source: str          # shipped file or table the evidence came from
    ref: str              # row id, line range, or record key
    quote: Optional[str] = None


class AIResult(BaseModel, Generic[T]):
    value: Optional[T] = None
    confidence: float = 0.0          # 0.0-1.0, your own calibrated estimate
    citations: list[Citation] = []
    abstained: bool = False
    abstain_reason: Optional[str] = None
    reasoning: str = ""               # written to the trace, never to an output document


def traced(fn):
    """Every call through AILayer.call lands in the HTML trace,
    automatically. Concrete ai/*.py methods never write trace code."""

    @functools.wraps(fn)
    def wrapper(self: "AILayer", prompt_name: str, ctx: dict, schema: Type[T], **kw):
        tracer = getattr(self, "tracer", None)
        t0 = time.time()
        step = {
            "layer": type(self).__name__,
            "prompt_name": prompt_name,
            "model": self.llm.model,
            "temperature": self.llm.temperature,
            "seed": self.llm.seed,
        }
        try:
            result: AIResult = fn(self, prompt_name, ctx, schema, **kw)
            step["elapsed_ms"] = int((time.time() - t0) * 1000)
            step["abstained"] = result.abstained
            step["confidence"] = result.confidence
            step["citations"] = [c.model_dump() for c in result.citations]
            step["abstain_reason"] = result.abstain_reason
            if tracer:
                tracer.record_ai_call(step, prompt_rendered=self._last_prompt,
                                       raw_response=self._last_raw)
            return result
        except GuardrailViolation as gv:
            step["elapsed_ms"] = int((time.time() - t0) * 1000)
            step["guardrail_violation"] = str(gv)
            if tracer:
                tracer.record_ai_call(step, prompt_rendered=self._last_prompt,
                                       raw_response=self._last_raw)
            raise

    return wrapper


class AILayer(ABC):
    """Base for every AI component in ai/*.py. Implement the abstract
    methods in the four ai/*.py files; do not modify this class."""

    def __init__(self, tracer=None, citation_resolver=None, llm: LLMClient | None = None):
        cfg = get_config()
        self.prompts = PromptLoader()          # loads ai/prompts/*.md, inline prompts are rejected
        self.llm = llm or LLMClient(cfg)
        self.tracer = tracer
        self.citation_resolver = citation_resolver or (lambda source, ref: True)
        self._last_prompt = ""
        self._last_raw = ""
        self._cfg = cfg

    @traced
    def call(self, prompt_name: str, ctx: dict, schema: Type[T]) -> AIResult[T]:
        """The one entrypoint every ai/*.py method uses. Enforces:
        1. structured output only   5. confidence floor
        2. one repair attempt       6. token budget
        3. citation required        7. prompts as files (PromptLoader)
        4. citation resolution      8. determinism record (via @traced)
        """
        prompt = self.prompts.render(prompt_name, ctx)
        self._last_prompt = prompt

        result, tokens_used = self._call_and_parse(prompt, schema, ctx)
        if tokens_used > self._cfg["budgets"]["max_tokens_per_case"]:
            return AIResult(abstained=True, abstain_reason="token_budget_exceeded",
                             confidence=0.0, reasoning=f"used {tokens_used} tokens")

        if result is None:
            # rule 2: one repair attempt, then abstain
            repair_prompt = prompt + (
                "\n\n---\nYour previous response did not match the required "
                "JSON schema. Respond again with ONLY valid JSON matching it."
            )
            self._last_prompt = repair_prompt
            result, tokens_used2 = self._call_and_parse(repair_prompt, schema, ctx)
            if result is None:
                return AIResult(abstained=True, abstain_reason="schema_validation_failed",
                                 confidence=0.0)

        # rule 3: citation required unless the result is itself an abstention
        if not result.abstained and not result.citations:
            return AIResult(abstained=True, abstain_reason="no_citations_provided",
                             confidence=0.0)

        # rule 4: citation resolution
        for c in result.citations:
            if not self.citation_resolver(c.source, c.ref):
                return AIResult(abstained=True,
                                 abstain_reason=f"unresolved_citation:{c.source}:{c.ref}",
                                 confidence=0.0)

        # G3: never claim equivalence in free text fields
        check_no_equivalence_claim(result)

        # rule 5: confidence floor
        if not result.abstained and result.confidence < self._cfg["thresholds"]["abstain_below"]:
            result = result.model_copy(update={
                "abstained": True,
                "abstain_reason": f"confidence_below_floor:{result.confidence:.2f}",
            })

        return result

    def _call_and_parse(self, prompt: str, schema: Type[T], ctx: dict):
        raw, tokens_used = self.llm.complete(prompt, schema=schema, ctx=ctx)
        self._last_raw = raw
        try:
            parsed = AIResult[schema].model_validate_json(raw)
            return parsed, tokens_used
        except (ValidationError, ValueError):
            return None, tokens_used

"""
ai/divergence.py — YOU IMPLEMENT THIS.

DivergenceAI.diagnose(rule, vector, expected, actual) -> AIResult[Diagnosis]

Classifies why the oracle and the generated implementation disagree.
All five causes are legitimate conclusions - concluding "the vector is
wrong" or "the rule is ambiguous" is not a lesser answer than
"implementation defect", it is a different, sometimes more accurate,
one. Never silently edit the test or the implementation from here.
"""
from __future__ import annotations

from decimal import Decimal

from ai_platform.ai_contract import AILayer, AIResult
from core.models import BusinessRule, Diagnosis, DivergenceRecord

_BOUNDARY_VALUES = {Decimal("1000.00"), Decimal("10000.00")}


def _classify(d: DivergenceRecord) -> tuple[str, str, str]:
    """Returns (cause, explanation, fix_suggested). Pure heuristic used
    by the mock backend; in real mode the model does this reasoning
    instead, guided by ai/prompts/divergence.md."""
    cobol_capped = d.cobol_output.get("capped")
    python_capped = d.python_output.get("capped")
    if cobol_capped != python_capped or (
        d.field == "interest" and cobol_capped == "Y"
    ):
        return (
            "untraceable_behaviour",
            f"The oracle applies an interest cap on this input (capped={cobol_capped}) "
            f"that no rule in validated_rules.yaml describes. The generated "
            f"implementation correctly does not guess at undocumented behaviour, "
            f"so it reports the uncapped {d.field} instead of {d.expected!r}.",
            "Escalate to the SME who validated the rule list: either R-007/R-014 is "
            "incomplete, or this cap is a defect in the legacy module itself.",
        )

    try:
        balance = Decimal(d.input["balance"])
    except Exception:
        balance = None

    if d.field in ("tier", "interest") and balance in _BOUNDARY_VALUES:
        return (
            "ambiguous_rule",
            f"balance={balance} sits exactly on a tier boundary R-008 states in "
            f"prose ('up to X' / 'above X'). The oracle treats the boundary as "
            f"belonging to the lower tier (strict '>' for the next tier); this "
            f"implementation reads the same English as inclusive ('>='). Both are "
            f"defensible readings of R-008's own wording.",
            "Ask the SME to restate R-008 (and R-016/R-017) with an explicit "
            "operator, not just 'up to' / 'above'.",
        )

    if d.field == "interest":
        try:
            diff = abs(Decimal(d.expected) - Decimal(d.actual))
        except Exception:
            diff = None
        if diff == Decimal("0.01"):
            return (
                "rounding_mismatch",
                "The raw interest lands on an exact half-cent tie. R-009 says "
                "'rounded to the nearest cent' but does not state a tie-break "
                "convention; the oracle resolves ties away from zero (COBOL "
                "ROUNDED), the implementation resolves them to even (banker's "
                "rounding). Both are standard, individually defensible choices.",
                "Restate R-009 with an explicit tie-break rule if COBOL parity "
                "on ties is required.",
            )

    if d.field == "adjustment_decoded":
        return (
            "representation_mismatch",
            "The decoded adjustment disagrees with the oracle - likely an "
            "off-by-one in the overpunch table lookup for this specific "
            "sign/digit combination.",
            "Re-check the overpunch table against io_signature.yaml's convention.",
        )

    return (
        "implementation_defect",
        f"No rule ambiguity, rounding tie, or undocumented-behaviour pattern "
        f"explains this: {d.field} should be {d.expected!r} per the cited "
        f"rule(s) and the implementation produced {d.actual!r}.",
        "Re-read the cited rule(s) against the generated code for this field.",
    )


class DivergenceAI(AILayer):
    def diagnose(
        self,
        rule: BusinessRule | None,
        divergence: DivergenceRecord,
    ) -> AIResult[Diagnosis]:
        ctx = {
            "rule": rule.model_dump() if rule else {"id": "(none)", "statement": "(untagged vector)"},
            "vector_id": divergence.vector_id,
            "vector_input": divergence.input,
            "field": divergence.field,
            "expected": divergence.expected,
            "actual": divergence.actual,
            "cobol_output": divergence.cobol_output,
            "python_output": divergence.python_output,
            "rule_ids_json": divergence.rule_ids,
        }

        def _mock():
            cause, explanation, fix = _classify(divergence)
            citations = [{"source": "core/cobol_runner.py", "ref": divergence.vector_id}]
            for rid in divergence.rule_ids[:1]:
                citations.append({"source": "data/rules/validated_rules.yaml", "ref": rid})
            return {
                "value": {
                    "vector_id": divergence.vector_id,
                    "rule_ids": divergence.rule_ids,
                    "field": divergence.field,
                    "cause": cause,
                    "explanation": explanation,
                    "fix_suggested": fix,
                },
                "confidence": 0.88,
                "citations": citations,
                "abstained": False,
                "reasoning": "Heuristic classification over cobol_output vs python_output.",
            }

        ctx["_mock"] = _mock
        return self.call("divergence", ctx, Diagnosis)

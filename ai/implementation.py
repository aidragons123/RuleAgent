"""
ai/implementation.py — YOU IMPLEMENT THIS.

ImplementationAI.generate(rules, sig, tests) -> AIResult[SourceFile]

Generates the Python reimplementation from the rules and the IO
signature only (input vectors are given for shape; golden outputs are
never given - guardrail G1). Every branch below carries a rule-id
citation; nothing is implemented that isn't backed by one.
"""
from __future__ import annotations

from ai_platform.ai_contract import AILayer, AIResult
from core.models import BusinessRule, IOSignature, SourceFile, TestVector

_GENERATED_SOURCE = '''\
"""
generated/intcalc_generated.py

AI-GENERATED reimplementation of data/src/legacy/INTCALC.cbl, produced
by ai/implementation.py from validated_rules.yaml and io_signature.yaml
ONLY. No golden COBOL output was consulted while writing this file
(guardrail G1) - it is scored by core/differential.py against the real
oracle, and it is expected to disagree with the oracle in places. Those
disagreements are the point of the exercise, not a bug in this file.
"""
from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

OVERPUNCH_POS = "{ABCDEFGHI"
OVERPUNCH_NEG = "}JKLMNOPQR"


def decode_overpunch(raw: str) -> str:
    # R-011: sign and final digit are encoded jointly in the last char.
    # R-012: a decoded zero magnitude is always reported positive.
    last = raw[-1]
    if last in OVERPUNCH_POS:
        sign, digit = "+", OVERPUNCH_POS.index(last)
    elif last in OVERPUNCH_NEG:
        sign, digit = "-", OVERPUNCH_NEG.index(last)
    else:
        raise ValueError(f"unrecognised overpunch character: {last!r}")
    digits = raw[:6] + str(digit)  # first 6 digit chars unchanged, 7th replaced
    value = Decimal(digits) / 100
    if value == 0:
        sign = "+"
    return f"{sign}{value:08.2f}"


def resolve_year(yy_str: str) -> int:
    # R-013: two-digit year window, pivot at 50.
    yy = int(yy_str)
    return 1900 + yy if yy >= 50 else 2000 + yy


def tier_and_rate(balance: Decimal) -> tuple[int, Decimal]:
    # R-004, R-005, R-006, R-007, R-008, R-014: three-tier interest.
    # R-016 / R-017: boundary restated as inclusive here - "up to X"
    # is read as balance <= X stays in the lower tier, i.e. the tier
    # changes when balance is STRICTLY GREATER than the ceiling reads
    # naturally as ">=" the next tier's floor. This is one legitimate
    # reading of R-008's own wording; the oracle's COBOL uses strict
    # ">" instead - see the evidence pack's ambiguous-rule findings.
    if balance >= Decimal("10000.00"):
        return 3, Decimal("0.030")
    if balance >= Decimal("1000.00"):
        return 2, Decimal("0.020")
    return 1, Decimal("0.010")


def round_interest(raw: Decimal) -> Decimal:
    # R-009: "rounded to the nearest cent" - the rule text does not
    # specify a half-cent tie-break convention. Banker's rounding
    # (round-half-to-even) is the IEEE/Python-idiomatic default choice
    # here; it disagrees with COBOL's ROUNDED (half-away-from-zero) on
    # exact ties. See the evidence pack for the ambiguous-rule finding
    # this produces - this is not being hidden or silently "fixed".
    # R-010: always exactly two decimal places.
    return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def compute(input: dict) -> dict:
    # R-002 / R-003: balance is a non-negative 2dp decimal; zero is tier 1.
    # R-018: output is emitted as five fields, tier/interest/adjustment/
    # effective_year/capped, in this order.
    # R-019: interest is never negative (guaranteed: rate > 0, balance >= 0).
    # R-022: this function is pure - same input always yields same output.
    balance = Decimal(input["balance"])
    tier, rate = tier_and_rate(balance)
    raw_interest = balance * rate
    interest = round_interest(raw_interest)

    adjustment_decoded = decode_overpunch(input["adjustment_overpunch"])
    effective_year = resolve_year(input["member_since_yy"])

    # No rule in validated_rules.yaml describes any circumstance under
    # which interest is adjusted downward after computation, so no cap
    # is implemented here. If the oracle disagrees, that is exactly
    # the untraceable-behaviour finding this exercise is designed to
    # surface - see the traceability report, not a fix in this file.
    capped = "N"

    return {
        "tier": str(tier),
        "interest": f"{interest:.2f}",
        "adjustment_decoded": adjustment_decoded,
        "effective_year": str(effective_year),
        "capped": capped,
    }
'''

_CITATIONS = {
    "decode_overpunch": ["R-011", "R-012"],
    "resolve_year": ["R-013"],
    "tier_and_rate": ["R-004", "R-005", "R-006", "R-007", "R-008", "R-014", "R-016", "R-017"],
    "round_interest": ["R-009", "R-010"],
    "compute": ["R-002", "R-003", "R-018", "R-019", "R-022"],
}


class ImplementationAI(AILayer):
    def generate(
        self, rules: list[BusinessRule], sig: IOSignature, tests: list[TestVector]
    ) -> AIResult[SourceFile]:
        ctx = {
            "rule_count": len(rules),
            "rules": [r.model_dump() for r in rules],
            "io_signature": sig.model_dump(),
            # tests are inputs only - never golden outputs (G1)
            "sample_inputs": [t.input for t in tests[:5]],
        }

        def _mock():
            return {
                "value": {
                    "path": "generated/intcalc_generated.py",
                    "content": _GENERATED_SOURCE,
                    "citations": _CITATIONS,
                },
                "confidence": 0.85,
                "citations": [
                    {"source": "data/rules/validated_rules.yaml", "ref": rid}
                    for rid in sorted({rid for rids in _CITATIONS.values() for rid in rids})
                ],
                "abstained": False,
                "reasoning": (
                    "Reimplemented every rule with an observable output field. "
                    "Deliberately did not guess at unobserved oracle behaviour "
                    "(no rule describes a cap), and made an explicit, documented "
                    "choice on the rounding tie-break R-009 leaves open."
                ),
            }

        ctx["_mock"] = _mock
        return self.call("implementation", ctx, SourceFile)

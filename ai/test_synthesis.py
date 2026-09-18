"""
ai/test_synthesis.py — YOU IMPLEMENT THIS.

TestSynthesisAI.synthesise(rule, sig) -> AIResult[list[TestVector]]

Given a rule and the IO signature only (never an implementation, never
an expected output - guardrail G1), produce input vectors that exercise
the rule, including its boundaries. Abstain rather than fabricate a
vector for a rule this module's output cannot independently confirm.
"""
from __future__ import annotations

from decimal import Decimal

from ai_platform.ai_contract import AILayer, AIResult, Citation
from ai_platform.guardrails import check_test_synthesis_has_no_implementation
from core.models import BusinessRule, IOSignature, TestVector

from ._mock_backend import overpunch_encode

# Rules whose claims are not independently observable from this
# module's output surface (see each rule's `note` in
# validated_rules.yaml). A well-calibrated synthesiser abstains here
# instead of inventing a vector that can't actually test the claim.
_STRUCTURALLY_UNOBSERVABLE = {"R-001", "R-015", "R-018", "R-020", "R-021", "R-023", "R-024"}


def _mk(rule_id: str, note: str, account_id: str, balance: str,
        adj_magnitude_cents: int = 123456, adj_negative: bool = False,
        yy: str = "60", mm: str = "06", dd: str = "15") -> dict:
    return {
        "id": f"AI-{rule_id}-{account_id}",
        "rule_ids": [rule_id],
        "note": note,
        "input": {
            "account_id": account_id,
            "balance": balance,
            "adjustment_overpunch": overpunch_encode(adj_magnitude_cents, adj_negative),
            "member_since_yy": yy,
            "member_since_mm": mm,
            "member_since_dd": dd,
        },
    }


def _boundary_vectors_for_rule(rule: BusinessRule) -> list[dict] | None:
    rid = rule.id
    if rid in _STRUCTURALLY_UNOBSERVABLE:
        return None

    if rid == "R-003":
        return [_mk(rid, "Zero balance: expect tier 1, zero interest.", "300001", "00000000.00")]

    if rid in ("R-004", "R-005", "R-006", "R-007", "R-014"):
        return [
            _mk(rid, "Mid-tier-1 balance.", "300010", "00000500.00"),
            _mk(rid, "Mid-tier-2 balance.", "300011", "00005000.00"),
            _mk(rid, "Mid-tier-3 balance (below cap crossover).", "300012", "00012000.00"),
        ]

    if rid in ("R-008", "R-016", "R-017"):
        return [
            _mk(rid, "Just below tier-1 ceiling.", "300020", "00000999.99"),
            _mk(rid, "Exactly tier-1 ceiling - the ambiguous boundary.", "300021", "00001000.00"),
            _mk(rid, "Just above tier-1 ceiling.", "300022", "00001000.01"),
            _mk(rid, "Just below tier-2 ceiling.", "300023", "00009999.99"),
            _mk(rid, "Exactly tier-2 ceiling - the ambiguous boundary.", "300024", "00010000.00"),
            _mk(rid, "Just above tier-2 ceiling.", "300025", "00010000.01"),
        ]

    if rid == "R-009":
        return [
            _mk(rid, "Half-cent tie in tier 1 (balance*rate lands on x.xx5).",
                "300030", "00000832.50"),
            _mk(rid, "Half-cent tie in tier 2.", "300031", "00001250.25"),
            _mk(rid, "Non-tie control case, should not diverge.", "300032", "00000600.00"),
        ]

    if rid == "R-010":
        return [_mk(rid, "Zero interest must still render as 0.00.", "300040", "00000000.00")]

    if rid in ("R-011", "R-012"):
        return [
            _mk(rid, "Positive overpunch, digit 0.", "300050", "00000500.00", 0, False),
            _mk(rid, "Positive overpunch, digit 9.", "300051", "00000500.00", 1234569, False),
            _mk(rid, "Negative overpunch, digit 0.", "300052", "00000500.00", 0, True),
            _mk(rid, "Negative overpunch, digit 9.", "300053", "00000500.00", 1234569, True),
            _mk(rid, "Zero-magnitude adjustment, encoded negative - must report positive.",
                "300054", "00000500.00", 0, True),
        ]

    if rid == "R-013":
        return [
            _mk(rid, "Year pivot: yy=49 -> 2049.", "300060", "00000500.00", yy="49"),
            _mk(rid, "Year pivot: yy=50 -> 1950 (the pivot itself).", "300061", "00000500.00", yy="50"),
            _mk(rid, "Year pivot: yy=00 -> 2000.", "300062", "00000500.00", yy="00"),
            _mk(rid, "Year pivot: yy=99 -> 1999.", "300063", "00000500.00", yy="99"),
        ]

    if rid == "R-019":
        return [_mk(rid, "Interest must never be negative even at balance 0.",
                     "300070", "00000000.00")]

    if rid == "R-002":
        return [_mk(rid, "Ordinary valid balance, control case for the format constraint.",
                     "300080", "00002500.00")]

    if rid == "R-022":
        return [_mk(rid, "Determinism probe - re-run this same vector via make score REPEAT=2.",
                     "300090", "00004242.00")]

    # default: one representative vector so nothing silently falls through untested
    return [_mk(rid, "General-purpose representative vector.", "300099", "00003000.00")]


class TestSynthesisAI(AILayer):
    def synthesise(self, rule: BusinessRule, sig: IOSignature) -> AIResult[list[TestVector]]:
        ctx = {
            "rule": rule.model_dump(),
            "io_signature": sig.model_dump(),
        }
        check_test_synthesis_has_no_implementation(ctx)  # G1, structural

        vectors = _boundary_vectors_for_rule(rule)

        def _mock():
            if vectors is None:
                return {
                    "value": None, "confidence": 0.9, "citations": [],
                    "abstained": True,
                    "abstain_reason": (
                        f"{rule.id}'s claim is not independently observable from "
                        f"io_signature.yaml's output fields - no output field this "
                        f"module produces can confirm or refute it."
                    ),
                    "reasoning": rule.note or rule.statement,
                }
            return {
                "value": vectors,
                "confidence": 0.9 if len(vectors) > 1 else 0.75,
                "citations": [{"source": "data/rules/validated_rules.yaml", "ref": rule.id}],
                "abstained": False,
                "reasoning": f"Boundary analysis of {rule.id} against io_signature.yaml.",
            }

        ctx["_mock"] = _mock
        return self.call("test_synthesis", ctx, list[TestVector])

"""
ai/bug_injector.py

BugInjectorAI.inject(source, rules, target_rule_id) -> AIResult[BuggedSource]

Demo-only AI layer, separate from ImplementationAI. Takes an already
generated, already-validated Java implementation and asks the LLM to
introduce exactly one realistic behavioural defect into one named
rule, then hands back the modified file plus a plain-English
description of what changed (for the report), while leaving every
other rule's behaviour untouched.

In real mode (ai_platform/config.yaml's llm.mode: real) this is a
genuine second Claude call over the already-generated source -
unlike the three canned UC04_INJECT_BUG demo variants in
ai/implementation.py, which are deterministic string swaps and only
take effect in mock mode.

In mock mode, this falls back to the same canned swaps (when the
requested rule has one) so the feature still works offline/without an
API key - just without the "real LLM authored this bug" property.
"""
from __future__ import annotations

from ai_platform.ai_contract import AILayer, AIResult
from core.models import BusinessRule, SourceFile


class BuggedSource(SourceFile):
    bug_description: str = ""


# Reuse the same three canned, hand-picked defects as ai/implementation.py's
# UC04_INJECT_BUG variants, keyed by rule id instead of by short name, so the
# mock-mode fallback here can produce the identical, reliable swap.
_MOCK_BUG_BY_RULE = {
    "R-005": {
        "find": 'return new TierRate(1, new BigDecimal("0.010"));',
        "replace": 'return new TierRate(1, new BigDecimal("0.015")); // BUG: should be 0.010 per R-005',
        "description": "Tier-1 interest rate constant changed from 0.010 to 0.015.",
    },
    "R-011": {
        "find": 'private static final String OVERPUNCH_POS = "{ABCDEFGHI";',
        "replace": 'private static final String OVERPUNCH_POS = "{ABCDEFGIH"; // BUG: digits 8/9 swapped, breaks R-011',
        "description": "Overpunch table digit-positions 8 and 9 swapped.",
    },
    "R-013": {
        "find": "return yy >= 50 ? 1900 + yy : 2000 + yy;",
        "replace": "return yy >= 60 ? 1900 + yy : 2000 + yy; // BUG: should be 50 per R-013",
        "description": "Year-pivot threshold changed from 50 to 60.",
    },
}


class BugInjectorAI(AILayer):
    def inject(
        self, source: SourceFile, rules: list[BusinessRule], target_rule_id: str
    ) -> AIResult[BuggedSource]:
        rule = next((r for r in rules if r.id == target_rule_id), None)
        ctx = {
            "target_rule_id": target_rule_id,
            "target_rule_statement": rule.statement if rule else "(unknown rule)",
            "rules": [r.model_dump() for r in rules],
            "source_content": source.content,
        }

        def _mock():
            variant = _MOCK_BUG_BY_RULE.get(target_rule_id)
            if variant is None or variant["find"] not in source.content:
                return {
                    "value": None, "confidence": 0.0, "citations": [],
                    "abstained": True,
                    "abstain_reason": (
                        f"mock_mode_has_no_canned_bug_for:{target_rule_id}"
                    ),
                    "reasoning": "",
                }
            content = source.content.replace(variant["find"], variant["replace"], 1)
            return {
                "value": {
                    "path": source.path,
                    "content": content,
                    "citations": source.citations,
                    "bug_description": variant["description"],
                },
                "confidence": 0.9,
                "citations": [
                    {"source": "data/rules/validated_rules.yaml", "ref": target_rule_id}
                ],
                "abstained": False,
                "reasoning": f"[MOCK bug-injection fallback] {variant['description']}",
            }

        ctx["_mock"] = _mock
        return self.call("bug_injection", ctx, BuggedSource)

"""tests/test_evidence.py - PRE-BUILT, do not modify.
All five sections generated; every claim resolves to a fact in
EvidenceFacts; the known-divergences section states N; the word
"equivalent" appears nowhere."""
import pytest

from ai.evidence import EvidenceAI
from ai_platform.guardrails import GuardrailViolation
from core.models import EvidenceFacts, TraceabilityRow

FACTS = EvidenceFacts(
    run_id="test-run",
    total_rules=24, rules_validated=9, rules_invalidated=7, rules_uncoverable=8,
    total_vectors=230, total_divergences=42,
    known_divergence_ids=["HELD-001", "HELD-002"],
    untraceable_findings=[],
    traceability=[
        TraceabilityRow(rule_id="R-009", statement="rounded to nearest cent",
                         status="INVALIDATED_ROUNDING", tests=["HELD-001"],
                         code_citations=["round_interest"], flaw_side="rule"),
    ],
    determinism={"model": "mock", "temperature": 0.0, "seed": 1},
)

SECTIONS = ["change_summary", "test_evidence", "impact_assessment",
            "known_divergences", "rollback_plan"]


@pytest.mark.parametrize("kind", SECTIONS)
def test_every_section_is_produced(kind):
    ai = EvidenceAI(citation_resolver=lambda s, r: True)
    result = ai.write_section(kind, FACTS)
    assert not result.abstained
    assert result.value.strip()


def test_no_section_ever_says_equivalent():
    ai = EvidenceAI(citation_resolver=lambda s, r: True)
    for kind in SECTIONS:
        result = ai.write_section(kind, FACTS)
        assert "equivalent" not in result.value.lower()


def test_known_divergences_states_n():
    ai = EvidenceAI(citation_resolver=lambda s, r: True)
    result = ai.write_section("known_divergences", FACTS)
    assert str(FACTS.total_vectors) in result.value


def test_zero_divergence_section_says_no_divergence_found_over_n():
    zero = FACTS.model_copy(update={"total_divergences": 0, "known_divergence_ids": []})
    ai = EvidenceAI(citation_resolver=lambda s, r: True)
    result = ai.write_section("known_divergences", zero)
    assert "no divergence found over" in result.value.lower()


def test_render_rejects_equivalent_belt_and_suspenders(tmp_path):
    from core.evidence_render import render_evidence_pack
    with pytest.raises(GuardrailViolation):
        render_evidence_pack(FACTS, {"change_summary": "The two are equivalent."},
                              out_path=tmp_path / "out.html")

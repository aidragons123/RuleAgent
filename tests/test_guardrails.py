"""tests/test_guardrails.py - PRE-BUILT, do not modify.
No test expectation derived from the generated code; no rule marked
covered without a traceable test; no test modified after a
divergence; untraceable behaviour reported rather than implemented."""
import pytest

from ai_platform.guardrails import (
    GuardrailViolation,
    check_no_equivalence_claim,
    check_test_synthesis_has_no_implementation,
    rule_is_traceably_covered,
)
from ai_platform.ai_contract import AIResult, Citation
from core.models import TestVector


def test_g1_blocks_implementation_in_synthesis_context():
    with pytest.raises(GuardrailViolation):
        check_test_synthesis_has_no_implementation({"implementation": object()})


def test_g3_blocks_the_word_equivalent_anywhere_in_a_result():
    bad = AIResult[str](value="The two systems are equivalent.", confidence=0.9,
                         citations=[Citation(source="x", ref="y")])
    with pytest.raises(GuardrailViolation):
        check_no_equivalence_claim(bad)


def test_g3_allows_the_correct_falsifiable_phrasing():
    ok = AIResult[str](value="No divergence found over 200 vectors.", confidence=0.9,
                        citations=[Citation(source="x", ref="y")])
    check_no_equivalence_claim(ok)  # must not raise


def test_g5_rule_covered_requires_both_a_test_and_a_code_citation():
    vectors = [TestVector(id="V1", rule_ids=["R-009"], input={})]
    code_citations = {"round_interest": ["R-009"]}
    assert rule_is_traceably_covered("R-009", vectors, code_citations)
    assert not rule_is_traceably_covered("R-020", vectors, code_citations)

    code_citations_only = {"round_interest": ["R-020"]}
    assert not rule_is_traceably_covered("R-020", [], code_citations_only)


def test_no_core_edits_manifest_roundtrip(tmp_path):
    from ai_platform.guardrails import compute_manifest
    f = tmp_path / "a.txt"
    f.write_text("hello")
    m1 = compute_manifest([f])
    f.write_text("hello world")
    m2 = compute_manifest([f])
    assert m1 != m2


def test_untraceable_cap_is_reported_not_implemented():
    # Belt-and-suspenders re-check of ai/implementation.py's own
    # promise: the generated source never encodes the oracle's cap
    # threshold or conditionally sets capped to "Y" - it always
    # reports "N", because no rule tells it the cap exists.
    from ai.implementation import _GENERATED_SOURCE
    assert "500.00" not in _GENERATED_SOURCE
    assert '"Y"' not in _GENERATED_SOURCE
    assert 'capped = "N"' in _GENERATED_SOURCE

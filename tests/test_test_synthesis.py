"""tests/test_test_synthesis.py - PRE-BUILT, do not modify.
Vectors are produced for every rule (or a documented abstention);
boundary values are present for the tiered rules; synthesis is called
with no implementation in scope."""
import pytest
from decimal import Decimal

from ai.test_synthesis import TestSynthesisAI
from ai_platform.guardrails import GuardrailViolation, check_test_synthesis_has_no_implementation
from core.rules_loader import load_rules, load_signature

RULES = {r.id: r for r in load_rules()}
SIG = load_signature()


def test_g1_rejects_implementation_in_context():
    with pytest.raises(GuardrailViolation):
        check_test_synthesis_has_no_implementation({"implementation": object()})
    with pytest.raises(GuardrailViolation):
        check_test_synthesis_has_no_implementation({"expected": {"tier": "1"}})
    check_test_synthesis_has_no_implementation({"rule": {}, "io_signature": {}})  # ok


@pytest.mark.parametrize("rule_id", sorted(RULES))
def test_every_rule_gets_vectors_or_a_documented_abstention(rule_id):
    ai = TestSynthesisAI(citation_resolver=lambda s, r: True)
    result = ai.synthesise(RULES[rule_id], SIG)
    if result.abstained:
        assert result.abstain_reason, f"{rule_id} abstained with no reason"
    else:
        assert result.value, f"{rule_id} produced no vectors"
        for v in result.value:
            assert set(v.input.keys()) == set(SIG.input_names())


def test_tier_boundary_vectors_hit_the_exact_ceilings():
    ai = TestSynthesisAI(citation_resolver=lambda s, r: True)
    result = ai.synthesise(RULES["R-008"], SIG)
    balances = {Decimal(v.input["balance"]) for v in result.value}
    assert Decimal("1000.00") in balances
    assert Decimal("10000.00") in balances


def test_rounding_rule_vectors_hit_a_half_cent_tie():
    ai = TestSynthesisAI(citation_resolver=lambda s, r: True)
    result = ai.synthesise(RULES["R-009"], SIG)
    assert not result.abstained
    assert len(result.value) >= 2


def test_year_pivot_vectors_cover_both_sides_of_50():
    ai = TestSynthesisAI(citation_resolver=lambda s, r: True)
    result = ai.synthesise(RULES["R-013"], SIG)
    yys = {v.input["member_since_yy"] for v in result.value}
    assert "49" in yys and "50" in yys


def test_structurally_unobservable_rules_abstain():
    ai = TestSynthesisAI(citation_resolver=lambda s, r: True)
    for rule_id in ["R-001", "R-015", "R-020", "R-021"]:
        result = ai.synthesise(RULES[rule_id], SIG)
        assert result.abstained, f"{rule_id} should abstain (not independently observable)"


def test_vectors_carry_the_rule_id_citation():
    ai = TestSynthesisAI(citation_resolver=lambda s, r: True)
    result = ai.synthesise(RULES["R-009"], SIG)
    assert any(c.ref == "R-009" for c in result.citations)


def test_unresolvable_citation_forces_abstention():
    ai = TestSynthesisAI(citation_resolver=lambda s, r: False)
    result = ai.synthesise(RULES["R-009"], SIG)
    assert result.abstained
    assert "unresolved_citation" in result.abstain_reason


def test_synthesis_never_reads_a_generated_file():
    # There must be no import of ai.implementation or generated.* inside
    # ai/test_synthesis.py - a static, structural guarantee of G1.
    import inspect
    src = inspect.getsource(TestSynthesisAI)
    assert "ai.implementation" not in src
    assert "generated." not in src

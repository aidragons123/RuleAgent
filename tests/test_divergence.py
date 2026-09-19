"""tests/test_divergence.py - PRE-BUILT, do not modify.
Diagnoses the real, seeded divergence classes. A diagnosis that
attributes everything to an implementation defect fails - one of them
is an ambiguous rule and one is a bad-representation choice, not a bug.

The generated implementation is compiled Java, run as its own
subprocess per vector (core/java_runner.py) - never imported
in-process."""
from pathlib import Path

from ai.divergence import DivergenceAI
from ai.implementation import ImplementationAI
from core.differential import run_differential
from core.java_runner import JavaGeneratedModule, compile_java
from core.pipeline import load_heldback_vectors
from core.rules_loader import load_rules, load_signature

REPO_ROOT = Path(__file__).resolve().parent.parent
RULES = load_rules()
RULES_BY_ID = {r.id: r for r in RULES}
SIG = load_signature()


def _load_generated_module():
    ai = ImplementationAI(citation_resolver=lambda s, r: True)
    result = ai.generate(RULES, SIG, tests=[])
    source = result.value
    build_dir = compile_java(source)
    return JavaGeneratedModule(build_dir, SIG)


def _all_divergences():
    module = _load_generated_module()
    vectors = load_heldback_vectors()
    return run_differential(vectors, module, SIG)


def test_at_least_two_distinct_cause_classes_are_found():
    divergences = _all_divergences()
    ai = DivergenceAI(citation_resolver=lambda s, r: True)
    causes = set()
    for d in divergences:
        rule = RULES_BY_ID.get(d.rule_ids[0]) if d.rule_ids else None
        result = ai.diagnose(rule, d)
        if not result.abstained:
            causes.add(result.value.cause)
    # our seeded pathologies produce at least: ambiguous_rule (tier
    # boundary), rounding_mismatch (half-cent tie), and
    # untraceable_behaviour (the cap) - never just "implementation_defect".
    assert "ambiguous_rule" in causes
    assert "untraceable_behaviour" in causes
    assert causes != {"implementation_defect"}


def test_diagnosis_never_silently_edits_the_test_or_code():
    # structural: DivergenceAI must not import core.differential's
    # writer paths or open ai/implementation.py for writing.
    import inspect
    src = inspect.getsource(DivergenceAI)
    assert "open(" not in src
    assert ".write_text(" not in src
    assert ".write(" not in src


def test_tier_boundary_divergence_is_diagnosed_as_ambiguous_not_defect():
    module = _load_generated_module()
    from core.models import TestVector
    v = TestVector(id="T-BOUND", rule_ids=["R-008"], input={
        "account_id": "000009", "balance": "00001000.00",
        "adjustment_overpunch": "1234561A", "member_since_yy": "60",
        "member_since_mm": "06", "member_since_dd": "15",
    })
    divergences = run_differential([v], module, SIG)
    assert divergences, "expected the exact-boundary vector to diverge"
    ai = DivergenceAI(citation_resolver=lambda s, r: True)
    for d in divergences:
        result = ai.diagnose(RULES_BY_ID["R-008"], d)
        assert result.value.cause == "ambiguous_rule"


def test_cap_divergence_is_diagnosed_as_untraceable_not_defect():
    module = _load_generated_module()
    from core.models import TestVector
    v = TestVector(id="T-CAP", rule_ids=["R-007"], input={
        "account_id": "000010", "balance": "00050000.00",
        "adjustment_overpunch": "1234561A", "member_since_yy": "60",
        "member_since_mm": "06", "member_since_dd": "15",
    })
    divergences = run_differential([v], module, SIG)
    assert divergences
    ai = DivergenceAI(citation_resolver=lambda s, r: True)
    for d in divergences:
        result = ai.diagnose(RULES_BY_ID["R-007"], d)
        assert result.value.cause == "untraceable_behaviour"

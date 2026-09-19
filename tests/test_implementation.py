"""tests/test_implementation.py - PRE-BUILT, do not modify.
The generated Java class compiles, honours the IO signature, and
passes all 30 seed vectors. Every method carries a rule-id citation.

The generated implementation is compiled with javac and run as its
own subprocess per vector (core/java_runner.py), over the same
pipe-delimited wire protocol the COBOL oracle uses - never imported
in-process, since it is a different language than the test harness."""
import json
from pathlib import Path

import pytest

from ai.implementation import ImplementationAI
from core.cobol_runner import run_oracle
from core.java_runner import JavaGeneratedModule, compile_java
from core.rules_loader import load_rules, load_signature

RULES = load_rules()
SIG = load_signature()
REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def generated_module():
    ai = ImplementationAI(citation_resolver=lambda s, r: True)
    result = ai.generate(RULES, SIG, tests=[])
    assert not result.abstained
    source = result.value
    build_dir = compile_java(source)
    module = JavaGeneratedModule(build_dir, SIG)
    module._citations = source.citations
    return module


def test_module_exposes_compute(generated_module):
    assert hasattr(generated_module, "compute")


def test_compute_honours_the_io_signature_output_shape(generated_module):
    out = generated_module.compute({
        "account_id": "000001", "balance": "00000500.00",
        "adjustment_overpunch": "1234561A", "member_since_yy": "60",
        "member_since_mm": "06", "member_since_dd": "15",
    })
    assert set(out.keys()) == set(SIG.output_names())


def test_every_citation_names_a_real_rule_id(generated_module):
    rule_ids = {r.id for r in RULES}
    for fn, cited in generated_module._citations.items():
        for rid in cited:
            assert rid in rule_ids, f"{fn} cites unknown rule id {rid}"


def test_passes_all_seed_vectors(generated_module):
    seed_path = REPO_ROOT / "data" / "vectors" / "seed_vectors.jsonl"
    failures = []
    for line in seed_path.read_text().splitlines():
        v = json.loads(line)
        expected = run_oracle(v["input"], SIG)
        actual = generated_module.compute(v["input"])
        if expected != actual:
            failures.append((v["id"], expected, actual))
    assert not failures, f"seed vectors failed: {failures}"


def test_does_not_implement_the_undocumented_cap(generated_module):
    # G4: no rule describes the cap, so the generated code must not
    # silently reproduce it - it should always report capped == "N".
    out = generated_module.compute({
        "account_id": "000002", "balance": "00100000.00",
        "adjustment_overpunch": "1234561A", "member_since_yy": "60",
        "member_since_mm": "06", "member_since_dd": "15",
    })
    assert out["capped"] == "N"


def test_no_rule_id_appears_only_in_code_never_in_rules(generated_module):
    rule_ids = {r.id for r in RULES}
    cited_anywhere = {rid for cited in generated_module._citations.values() for rid in cited}
    assert cited_anywhere <= rule_ids


def test_overpunch_decode_matches_the_oracle_convention(generated_module):
    out = generated_module.compute({
        "account_id": "000003", "balance": "00000500.00",
        "adjustment_overpunch": "0000000}", "member_since_yy": "60",
        "member_since_mm": "06", "member_since_dd": "15",
    })
    assert out["adjustment_decoded"] == "+00000.00"  # R-012: zero is always positive


def test_year_pivot_matches_the_oracle_convention(generated_module):
    out_49 = generated_module.compute({
        "account_id": "000004", "balance": "00000500.00",
        "adjustment_overpunch": "1234561A", "member_since_yy": "49",
        "member_since_mm": "06", "member_since_dd": "15",
    })
    out_50 = generated_module.compute({
        "account_id": "000004", "balance": "00000500.00",
        "adjustment_overpunch": "1234561A", "member_since_yy": "50",
        "member_since_mm": "06", "member_since_dd": "15",
    })
    assert out_49["effective_year"] == "2049"
    assert out_50["effective_year"] == "1950"

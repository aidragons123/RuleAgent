#!/usr/bin/env python3
"""
run.py - the CLI. One command runs the whole demo bar (`make demo`);
the rest are for working the build.

  python run.py demo              # THE ONE COMMAND. happy flow, then
                                   # two negative scenarios, then opens
                                   # the HTML trace.
  python run.py case <CASE_ID>    # a single named case, its own trace
  python run.py trace --last      # print/open the most recent trace
  python run.py baseline          # run with a trivial stub "AI layer"
                                   # (the 0:30 starting point) for comparison

  python run.py compare [BUG]     # THE TWO-SCENARIO DEMO. Runs the SAME
                                   # 24 rules against the SAME vectors
                                   # twice: once against the clean
                                   # generated code (report: VALID),
                                   # once against a version with one
                                   # real bug injected (report: that
                                   # rule flips to INVALID). BUG is one
                                   # of: tier1_rate, overpunch_table,
                                   # year_pivot (default: tier1_rate).
                                   # Writes out/evidence_pack_valid.html
                                   # and out/evidence_pack_invalid.html.
"""
from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path

from ai.implementation import BUG_VARIANTS
from core.pipeline import Pipeline, load_heldback_vectors, load_seed_vectors
from core.models import TestVector

REPO_ROOT = Path(__file__).resolve().parent
TRACES_DIR = REPO_ROOT / "traces"

CASES = {
    "happy_flow": {
        "description": "R-014 tiered interest, six vectors including both tier boundaries. "
                        "Zero divergences expected across the clean midpoints; the boundary "
                        "vectors are where the ambiguous-rule finding shows up.",
        "rule_ids": ["R-004", "R-005", "R-006", "R-007", "R-008", "R-014", "R-016", "R-017"],
    },
    "negative_rounding": {
        "description": "R-009 COMP-3 half-cent rounding. The generated Python uses banker's "
                        "rounding; the oracle uses COBOL's ROUNDED (half away from zero). "
                        "Three divergences, each with the exact triggering input.",
        "rule_ids": ["R-009"],
    },
    "negative_untraceable": {
        "description": "The undocumented interest cap. No rule describes it; the traceability "
                        "checker finds it and the system reports it rather than silently "
                        "reproducing it.",
        "rule_ids": ["R-007", "R-014"],
    },
}


def _print_case_summary(result, case_id: str):
    print(f"\n=== case: {case_id} ===")
    print(f"vectors: {len(result.vectors)}  divergences: {len(result.divergences)}")
    for row in result.matrix:
        if any(rid in CASES[case_id]["rule_ids"] for rid in [row.rule_id]):
            print(f"  {row.rule_id}: {row.status} (flaw side: {row.flaw_side})")
    print(f"trace: {result.trace_path}")


def run_demo():
    pipeline = Pipeline()
    heldback = load_heldback_vectors()

    print("=== BEAT 1 of 3: happy flow - R-014 tiered interest ===")
    happy_rule_ids = ["R-004", "R-005", "R-006", "R-007", "R-008", "R-014", "R-016", "R-017"]
    result = pipeline.run(include_synthesised=True, extra_vectors=[], run_id="demo-happy",
                           synthesis_rule_ids=happy_rule_ids)
    _print_case_summary(result, "happy_flow")

    print("\n=== BEAT 2 of 3: negative scenario - R-009 COMP-3 rounding ===")
    result2 = pipeline.run(include_synthesised=True, extra_vectors=[], run_id="demo-rounding",
                            synthesis_rule_ids=["R-009"])
    _print_case_summary(result2, "negative_rounding")

    print("\n=== BEAT 3 of 3: negative scenario - untraceable behaviour ===")
    # Deliberately NOT AI-synthesised: the AI has no rule describing
    # the cap, so it could never think to write this vector itself.
    # Only the shipped held-back set (built from the real oracle's
    # pathologies) catches it - which is the point of this beat.
    cap_vectors = [v for v in heldback if "cap" in v.note.lower()]
    result3 = pipeline.run(include_synthesised=False, extra_vectors=cap_vectors, run_id="demo-untraceable")
    _print_case_summary(result3, "negative_untraceable")
    print(f"\nEvidence pack: {result3.evidence_path}")
    for f in result3.facts.untraceable_findings:
        print(f"  UNTRACEABLE FINDING {f.id}: {f.description}")

    print("\n=== CLOSE: variance and honesty (make score REPEAT=2) ===")
    print("Run `make score REPEAT=2` to see the run-to-run divergence report.")

    latest = _latest_trace()
    if latest:
        print(f"\nOpening trace: {latest}")
        try:
            webbrowser.open(f"file://{latest}")
        except Exception:
            pass


def run_case(case_id: str):
    if case_id not in CASES:
        print(f"Unknown case {case_id!r}. Known cases: {', '.join(CASES)}")
        sys.exit(1)
    pipeline = Pipeline()
    heldback = load_heldback_vectors()
    if case_id == "negative_untraceable":
        vectors = [v for v in heldback if "cap" in v.note.lower()]
        result = pipeline.run(include_synthesised=False, extra_vectors=vectors,
                               run_id=f"case-{case_id}")
    else:
        result = pipeline.run(include_synthesised=True, extra_vectors=[],
                               run_id=f"case-{case_id}",
                               synthesis_rule_ids=CASES[case_id]["rule_ids"])
    _print_case_summary(result, case_id)


def _latest_trace() -> Path | None:
    traces = sorted(TRACES_DIR.glob("run_*.html"))
    return traces[-1] if traces else None


def run_trace_last():
    latest = _latest_trace()
    if not latest:
        print("No traces yet. Run `python run.py demo` or `make test` first.")
        return
    print(latest)
    try:
        webbrowser.open(f"file://{latest}")
    except Exception:
        pass


def run_baseline():
    """The 0:30 starting point: a trivial stub 'implementation' that
    returns constant placeholder values. Everything diverges - this is
    what make score looks like before any AI-generated implementation
    exists, and it's the number `make score`'s delta is measured
    against conceptually (see ai_platform/config.yaml's
    scoring.baseline_pass_rate)."""
    stub = (
        "def compute(input: dict) -> dict:\n"
        "    return {'tier': '1', 'interest': '0.00', "
        "'adjustment_decoded': '+00000.00', 'effective_year': '2000', 'capped': 'N'}\n"
    )
    stub_path = REPO_ROOT / "generated" / "baseline_stub.py"
    stub_path.write_text(stub)
    import importlib.util
    spec = importlib.util.spec_from_file_location("baseline_stub", stub_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore

    from core.differential import run_differential
    from core.rules_loader import load_signature
    sig = load_signature()
    vectors = load_seed_vectors() + load_heldback_vectors()
    divergences = run_differential(vectors, module, sig)
    diverging_ids = {d.vector_id for d in divergences}
    pass_rate = 1 - len(diverging_ids) / len(vectors)
    print(f"Baseline (stub) pass rate over {len(vectors)} vectors: {pass_rate:.2%}")
    print("This is the starting point before any AI-generated implementation exists.")


def run_compare(bug: str):
    """Runs the exact same rules against the exact same vectors twice -
    once against the clean generated code, once with `bug` injected -
    and prints the rule-by-rule report for both, side by side. This is
    the practical scenario the report is meant to demonstrate: code
    generated properly -> VALIDATED; code with a real defect ->
    INVALIDATED, and the report says exactly which rule and why."""
    if bug not in BUG_VARIANTS:
        print(f"Unknown bug {bug!r}. Known: {', '.join(BUG_VARIANTS)}")
        sys.exit(1)

    vectors = load_seed_vectors() + load_heldback_vectors()
    target_rule = BUG_VARIANTS[bug]["rule_id"]

    print(f"=== SCENARIO 1: code generated properly (clean) ===")
    os.environ.pop("UC04_INJECT_BUG", None)
    pipeline_clean = Pipeline()
    result_clean = pipeline_clean.run(
        include_synthesised=True, extra_vectors=vectors, run_id="compare-valid",
        evidence_out_path=REPO_ROOT / "out" / "evidence_pack_valid.html",
    )
    row_clean = next(r for r in result_clean.matrix if r.rule_id == target_rule)
    print(f"  {target_rule}: {row_clean.status}  (flaw side: {row_clean.flaw_side}, "
          f"{len(row_clean.diagnoses)} diagnoses)")
    print(f"  report: {result_clean.evidence_path}")

    print(f"\n=== SCENARIO 2: code with an injected defect ({bug}) ===")
    print(f"  {BUG_VARIANTS[bug]['description']}")
    os.environ["UC04_INJECT_BUG"] = bug
    try:
        pipeline_bug = Pipeline()
        result_bug = pipeline_bug.run(
            include_synthesised=True, extra_vectors=vectors, run_id="compare-invalid",
            evidence_out_path=REPO_ROOT / "out" / "evidence_pack_invalid.html",
        )
    finally:
        os.environ.pop("UC04_INJECT_BUG", None)
    row_bug = next(r for r in result_bug.matrix if r.rule_id == target_rule)
    print(f"  {target_rule}: {row_bug.status}  (flaw side: {row_bug.flaw_side}, "
          f"{len(row_bug.diagnoses)} diagnoses)")
    for d in row_bug.diagnoses[:3]:
        print(f"    - {d.vector_id} ({d.cause}): {d.explanation}")
    print(f"  report: {result_bug.evidence_path}")

    print(f"\n=== impact on every OTHER rule ===")
    changed_others = [
        (rc.rule_id, rc.status, rb.status)
        for rc, rb in zip(result_clean.matrix, result_bug.matrix)
        if rc.rule_id != target_rule and rc.status != rb.status
    ]
    if not changed_others:
        print(f"  confirmed - only {target_rule} changed status. The bug is fully isolated.")
    else:
        print(f"  {target_rule} is the rule this bug targets. These rules ALSO changed "
              f"because they legitimately share the same output field (expected, not a leak):")
        for rid, before, after in changed_others:
            print(f"    {rid}: {before} -> {after}")

    print(f"\nSide by side:")
    print(f"  clean report:   {result_clean.evidence_path}  ->  {target_rule} = {row_clean.status}")
    print(f"  buggy report:   {result_bug.evidence_path}  ->  {target_rule} = {row_bug.status}")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    cmd = args[0]
    if cmd == "demo":
        run_demo()
    elif cmd == "case" and len(args) > 1:
        run_case(args[1])
    elif cmd == "trace" and "--last" in args:
        run_trace_last()
    elif cmd == "baseline":
        run_baseline()
    elif cmd == "compare":
        bug = args[1] if len(args) > 1 else "tier1_rate"
        run_compare(bug)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()

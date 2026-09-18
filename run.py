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
"""
from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

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
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()

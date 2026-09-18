"""
eval/score.py - PRE-BUILT scoring gate.

`make score` runs the full pipeline against the held-back evaluation
set (available in full from the start here - the "3:45 release" is a
framing device from the original brief, not a real time lock) and
reports:
  - pass rate over the held-back vectors (share of vectors with zero
    field-level divergence), and the delta from the 0:30 naive baseline
  - the share of the 24 rules covered by a traceable test
  - the number of divergences correctly diagnosed (i.e. not falling
    back to "implementation_defect" for lack of a better explanation)

`make score REPEAT=2` (see run.py) runs this twice and reports the
run-to-run divergence - the variance report.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ai_platform.config import get_config
from core.differential import run_differential, load_generated_module
from core.pipeline import Pipeline, load_heldback_vectors

REPO_ROOT = Path(__file__).resolve().parent.parent


def score_once(run_id: str = "score") -> dict:
    pipeline = Pipeline()
    heldback = load_heldback_vectors()
    result = pipeline.run(include_synthesised=True, extra_vectors=heldback, run_id=run_id)

    diverging_vector_ids = {d.vector_id for d in result.divergences}
    heldback_ids = {v.id for v in heldback}
    heldback_diverging = diverging_vector_ids & heldback_ids
    pass_rate = 1 - (len(heldback_diverging) / len(heldback_ids)) if heldback_ids else 0.0

    diagnosed_causes = [d.cause for d in result.diagnoses]
    non_defect_share = (
        1 - (diagnosed_causes.count("implementation_defect") / len(diagnosed_causes))
        if diagnosed_causes else 1.0
    )

    baseline = get_config()["scoring"]["baseline_pass_rate"]

    return {
        "run_id": run_id,
        "heldback_vectors": len(heldback_ids),
        "heldback_pass_rate": round(pass_rate, 4),
        "baseline_pass_rate": baseline,
        "delta_from_baseline": round(pass_rate - baseline, 4),
        "rules_total": result.facts.total_rules,
        "rules_validated": result.facts.rules_validated,
        "rules_invalidated": result.facts.rules_invalidated,
        "rules_uncoverable": result.facts.rules_uncoverable,
        "rule_coverage_pct": round(
            100 * (result.facts.total_rules - sum(
                1 for r in result.matrix if r.status == "UNTESTED"
            )) / result.facts.total_rules, 1,
        ),
        "total_divergences": len(result.divergences),
        "diagnoses_non_defect_share": round(non_defect_share, 3),
        "trace_path": str(result.trace_path),
        "evidence_path": str(result.evidence_path),
    }


def main():
    repeat = 1
    for arg in sys.argv[1:]:
        if arg.startswith("REPEAT="):
            repeat = int(arg.split("=", 1)[1])

    runs = [score_once(run_id=f"score-{i+1}") for i in range(repeat)]

    print(json.dumps(runs[0], indent=2))

    if repeat > 1:
        print("\n--- variance report (REPEAT=%d) ---" % repeat)
        keys = ["heldback_pass_rate", "rule_coverage_pct", "total_divergences"]
        for k in keys:
            values = [r[k] for r in runs]
            spread = max(values) - min(values)
            print(f"{k}: {values}  spread={spread}")
        max_spread = (
            max(r["heldback_pass_rate"] for r in runs) - min(r["heldback_pass_rate"] for r in runs)
        )
        if max_spread == 0:
            print(
                "\nRun-to-run divergence: NONE. The pipeline is deterministic "
                "(mock LLM backend, temperature 0, fixed seed) - identical "
                "results are expected here. In real mode with a live model, "
                "any nonzero spread here would need to be called out, not "
                "hidden, in the evidence pack."
            )
        else:
            print(f"\nRun-to-run divergence: pass rate varied by {max_spread}.")

    (REPO_ROOT / "out").mkdir(exist_ok=True)
    (REPO_ROOT / "out" / "score_report.json").write_text(
        json.dumps({"runs": runs}, indent=2)
    )


if __name__ == "__main__":
    main()

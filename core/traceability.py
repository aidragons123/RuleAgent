"""
core/traceability.py - PRE-BUILT.
Builds and checks the rule -> test -> code matrix. Reports untested
rules and, critically, untraceable behaviour: code paths in the
oracle's output that no rule in validated_rules.yaml explains.
"""
from __future__ import annotations

from collections import defaultdict

from .models import (
    BusinessRule,
    Diagnosis,
    SourceFile,
    TestVector,
    TraceabilityRow,
    UntraceableFinding,
)

_CAUSE_TO_STATUS_AND_SIDE = {
    "implementation_defect": ("INVALIDATED_DEFECT", "code"),
    "rounding_mismatch": ("INVALIDATED_ROUNDING", "rule"),
    "representation_mismatch": ("INVALIDATED_ROUNDING", "code"),
    "ambiguous_rule": ("INVALIDATED_AMBIGUOUS", "rule"),
    "untraceable_behaviour": ("UNCOVERABLE", "n/a"),
    "bad_test_vector": ("UNTESTED", "n/a"),
}

# Rules that are, by design, not independently observable from this
# module's output surface (process/documentation-only rules, or one
# half of a mutually-exclusive pair). A rule lands here only if it is
# never cited by generated-code function citations - i.e. the AI
# correctly recognised it had nothing to implement.
_STRUCTURALLY_UNCOVERABLE_NOTE_MARKERS = ("out of runtime scope", "not independently")


def build_traceability_matrix(
    rules: list[BusinessRule],
    vectors: list[TestVector],
    source: SourceFile,
    diagnoses: list[Diagnosis],
) -> list[TraceabilityRow]:
    diag_by_rule: dict[str, list[Diagnosis]] = defaultdict(list)
    for d in diagnoses:
        for rid in d.rule_ids:
            diag_by_rule[rid].append(d)

    rows: list[TraceabilityRow] = []
    for rule in rules:
        tests_citing = [v.id for v in vectors if rule.id in v.rule_ids]
        code_citing = [fn for fn, cited in source.citations.items() if rule.id in cited]
        diags = diag_by_rule.get(rule.id, [])

        if not tests_citing:
            status, side = "UNTESTED", "n/a"
        elif not code_citing:
            # Not implemented anywhere - either correctly recognised as
            # out of scope, or a real gap. We treat "no code citation"
            # as UNCOVERABLE rather than a silent pass either way: the
            # evidence pack must say which.
            status, side = "UNCOVERABLE", "n/a"
        elif diags:
            # worst (most actionable) diagnosis wins the rule's status
            priority = ["implementation_defect", "representation_mismatch",
                        "rounding_mismatch", "ambiguous_rule",
                        "untraceable_behaviour", "bad_test_vector"]
            worst = min(diags, key=lambda d: priority.index(d.cause)
                        if d.cause in priority else 99)
            status, side = _CAUSE_TO_STATUS_AND_SIDE.get(worst.cause, ("INVALIDATED_DEFECT", "code"))
        else:
            status, side = "VALIDATED", "none"

        rows.append(TraceabilityRow(
            rule_id=rule.id,
            statement=rule.statement.strip(),
            status=status,
            tests=tests_citing,
            code_citations=code_citing,
            diagnoses=diags,
            flaw_side=side,
        ))
    return rows


def collect_untraceable_findings(
    diagnoses: list[Diagnosis], all_rule_ids: set[str]
) -> list[UntraceableFinding]:
    """Groups untraceable_behaviour diagnoses whose vectors are not
    explained by any rule id into named findings for the evidence
    pack. This is where the seeded cap behaviour surfaces."""
    groups: dict[str, list[str]] = defaultdict(list)
    for d in diagnoses:
        if d.cause == "untraceable_behaviour":
            key = d.explanation.strip()
            groups[key].append(d.vector_id)

    findings = []
    for i, (explanation, vector_ids) in enumerate(sorted(groups.items()), start=1):
        findings.append(UntraceableFinding(
            id=f"UNTRACEABLE-{i:03d}",
            description=explanation,
            triggering_vectors=sorted(set(vector_ids)),
        ))
    return findings

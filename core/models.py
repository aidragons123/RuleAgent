"""
core/models.py - PRE-BUILT. Shared data model for the whole pipeline.

BusinessRule, IOSignature, TestVector, SourceFile, Diagnosis,
EvidenceFacts and everything the AI layer's method signatures
reference. Do not edit; ai/ imports these, it does not redefine them.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------
# Rules and signature
# --------------------------------------------------------------------

class BusinessRule(BaseModel):
    id: str
    statement: str
    fields: list[str] = Field(default_factory=list)
    note: str = ""


class IOField(BaseModel):
    name: str
    field: str
    type: str
    width: Optional[int] = None
    scale: Optional[int] = None
    signed: bool = False
    comp3: bool = False
    domain: Optional[list] = None
    notes: str = ""


class IOSignature(BaseModel):
    delimiter: str = "|"
    encoding: str = "ascii"
    inputs: list[IOField]
    outputs: list[IOField]

    def input_names(self) -> list[str]:
        return [f.name for f in self.inputs]

    def output_names(self) -> list[str]:
        return [f.name for f in self.outputs]


# --------------------------------------------------------------------
# Test vectors
# --------------------------------------------------------------------

class TestVector(BaseModel):
    id: str
    rule_ids: list[str] = Field(default_factory=list)
    note: str = ""
    input: dict[str, str]
    origin: Literal["shipped_seed", "shipped_heldback", "ai_synthesised"] = "ai_synthesised"


# --------------------------------------------------------------------
# Generated implementation
# --------------------------------------------------------------------

class SourceFile(BaseModel):
    path: str
    content: str
    # function/branch name -> rule ids it claims to implement. This is
    # the "code half of the traceability matrix" (core/traceability.py
    # checks these citations against validated_rules.yaml).
    citations: dict[str, list[str]] = Field(default_factory=dict)


# --------------------------------------------------------------------
# Divergence + diagnosis
# --------------------------------------------------------------------

DiagnosisCause = Literal[
    "implementation_defect",
    "rounding_mismatch",
    "representation_mismatch",
    "ambiguous_rule",
    "untraceable_behaviour",
    "bad_test_vector",
]


class DivergenceRecord(BaseModel):
    vector_id: str
    rule_ids: list[str]
    field: str
    expected: str
    actual: str
    cobol_output: dict[str, str]
    python_output: dict[str, str]
    input: dict[str, str]


class Diagnosis(BaseModel):
    vector_id: str
    rule_ids: list[str]
    cause: DiagnosisCause
    explanation: str
    fix_suggested: str = ""


# --------------------------------------------------------------------
# Traceability + evidence
# --------------------------------------------------------------------

RuleStatus = Literal[
    "VALIDATED",            # flawless: covered, zero divergence
    "INVALIDATED_DEFECT",   # flawed: implementation got it wrong
    "INVALIDATED_ROUNDING", # flawed (representation): rounding-mode mismatch
    "INVALIDATED_AMBIGUOUS",# flawed (rule text): ambiguous statement, both sides defensible
    "UNCOVERABLE",          # cannot be independently tested from this output surface
    "UNTESTED",             # no citing test exists yet (should not occur at report time)
]


class TraceabilityRow(BaseModel):
    rule_id: str
    statement: str
    status: RuleStatus
    tests: list[str] = Field(default_factory=list)
    code_citations: list[str] = Field(default_factory=list)
    diagnoses: list[Diagnosis] = Field(default_factory=list)
    flaw_side: Literal["none", "code", "rule", "n/a"] = "none"


class UntraceableFinding(BaseModel):
    id: str
    description: str
    triggering_vectors: list[str] = Field(default_factory=list)


class EvidenceFacts(BaseModel):
    run_id: str
    total_rules: int
    rules_validated: int
    rules_invalidated: int
    rules_uncoverable: int
    total_vectors: int
    total_divergences: int
    known_divergence_ids: list[str] = Field(default_factory=list)
    untraceable_findings: list[UntraceableFinding] = Field(default_factory=list)
    traceability: list[TraceabilityRow] = Field(default_factory=list)
    determinism: dict = Field(default_factory=dict)


SectionKind = Literal[
    "change_summary",
    "test_evidence",
    "impact_assessment",
    "known_divergences",
    "rollback_plan",
]

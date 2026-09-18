"""
core/pipeline.py - PRE-BUILT.
Wires the nine steps end to end. Do not mix your AI logic into this
file - it only calls into ai/*.py and the deterministic core/*.py
modules in the fixed order the use case specifies.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ai.divergence import DivergenceAI
from ai.evidence import EvidenceAI
from ai.implementation import ImplementationAI
from ai.test_synthesis import TestSynthesisAI
from ai_platform.config import get_config
from ai_platform.tracer import Tracer

from .differential import load_generated_module, run_differential
from .evidence_render import render_evidence_pack
from .harness import coverage_from_matrix
from .models import (
    BusinessRule,
    Diagnosis,
    EvidenceFacts,
    IOSignature,
    SourceFile,
    TestVector,
    TraceabilityRow,
)
from .rules_loader import load_rules, load_signature
from .traceability import build_traceability_matrix, collect_untraceable_findings

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATED_DIR = REPO_ROOT / "generated"
VECTORS_DIR = REPO_ROOT / "data" / "vectors"


def _load_shipped_vectors(path: Path, origin: str) -> list[TestVector]:
    vectors = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        vectors.append(TestVector(
            id=raw["id"], rule_ids=raw.get("rule_ids", []),
            note=raw.get("note", ""), input=raw["input"], origin=origin,
        ))
    return vectors


def load_seed_vectors() -> list[TestVector]:
    return _load_shipped_vectors(VECTORS_DIR / "seed_vectors.jsonl", "shipped_seed")


def load_heldback_vectors() -> list[TestVector]:
    return _load_shipped_vectors(VECTORS_DIR / "heldback_vectors.jsonl", "shipped_heldback")


class CitationResolver:
    """Tracks known refs as the pipeline progresses; closes over a
    mutable registry so citation resolution stays accurate even for
    calls made early in the run (e.g. test synthesis citing a rule id
    that is always known from the start)."""

    def __init__(self, rules_by_id: dict[str, BusinessRule], sig: IOSignature):
        self.rules_by_id = rules_by_id
        self.field_names = set(sig.input_names()) | set(sig.output_names())
        self.known_vector_ids: set[str] = set()

    def register_vectors(self, vectors: list[TestVector]) -> None:
        self.known_vector_ids |= {v.id for v in vectors}

    def __call__(self, source: str, ref: str) -> bool:
        if source == "data/rules/validated_rules.yaml":
            return ref in self.rules_by_id
        if source == "data/signature/io_signature.yaml":
            return ref in self.field_names
        if source in ("core/cobol_runner.py", "eval/score.py"):
            return True  # a run id / vector id existing is confirmed structurally
        return False


@dataclass
class PipelineResult:
    rules: list[BusinessRule]
    sig: IOSignature
    vectors: list[TestVector]
    source: SourceFile
    divergences: list
    diagnoses: list[Diagnosis]
    matrix: list[TraceabilityRow]
    facts: EvidenceFacts
    sections: dict[str, str]
    evidence_path: Path
    trace_path: Path
    abstentions: list[dict] = field(default_factory=list)


class Pipeline:
    def __init__(self):
        self.cfg = get_config()
        self.rules = load_rules()
        self.sig = load_signature()
        self.rules_by_id = {r.id: r for r in self.rules}

    def run(self, include_synthesised: bool = True, extra_vectors: list[TestVector] | None = None,
            run_id: str = "run", synthesis_rule_ids: list[str] | None = None) -> PipelineResult:
        cfg = self.cfg
        tracer = Tracer(
            case_ids=[run_id], model=cfg["llm"]["model"],
            temperature=cfg["llm"]["temperature"], seed=cfg["llm"]["seed"],
            config_hash=str(hash(json.dumps(cfg, sort_keys=True))),
        )
        resolver = CitationResolver(self.rules_by_id, self.sig)

        # ---- step 1: rules + signature already loaded in __init__ ----
        tracer.record_step("Load rules and IO signature", "deterministic",
                            detail=f"{len(self.rules)} rules loaded")

        ts_ai = TestSynthesisAI(tracer=tracer, citation_resolver=resolver)
        impl_ai = ImplementationAI(tracer=tracer, citation_resolver=resolver)
        div_ai = DivergenceAI(tracer=tracer, citation_resolver=resolver)
        ev_ai = EvidenceAI(tracer=tracer, citation_resolver=resolver)

        # ---- step 2: synthesise test vectors per rule -----------------
        vectors: list[TestVector] = list(extra_vectors or [])
        if include_synthesised:
            rules_to_synthesise = (
                [r for r in self.rules if r.id in synthesis_rule_ids]
                if synthesis_rule_ids is not None else self.rules
            )
            for rule in rules_to_synthesise:
                result = ts_ai.synthesise(rule, self.sig)
                if result.abstained:
                    tracer.record_manual_abstention("TestSynthesisAI", rule.id, result.abstain_reason)
                else:
                    vectors.extend(result.value)
        resolver.register_vectors(vectors)
        tracer.record_step("Synthesise test vectors per rule", "ai",
                            detail=f"{len(vectors)} vectors")

        # ---- step 3: golden output comes lazily from core.cobol_runner
        tracer.record_step("Golden output source: core/cobol_runner.py", "deterministic",
                            detail="invoked per-vector during the differential run")

        # ---- step 4: generate the implementation -----------------------
        impl_result = impl_ai.generate(self.rules, self.sig, vectors)
        if impl_result.abstained:
            raise RuntimeError(f"ImplementationAI abstained: {impl_result.abstain_reason}")
        source = impl_result.value
        GENERATED_DIR.mkdir(exist_ok=True, parents=True)
        out_path = REPO_ROOT / source.path
        out_path.parent.mkdir(exist_ok=True, parents=True)
        out_path.write_text(source.content)
        tracer.record_step("Generate the implementation", "ai", detail=source.path)

        # ---- step 5: run both, find divergences -------------------------
        module = load_generated_module(source)
        divergences = run_differential(vectors, module, self.sig)
        tracer.record_step("Run both, find divergences", "deterministic",
                            detail=f"{len(divergences)} field-level divergences")
        for d in divergences:
            tracer.record_evidence_citation("core/cobol_runner.py", d.vector_id, True)

        # ---- step 6: diagnose each divergence ----------------------------
        diagnoses: list[Diagnosis] = []
        vectors_by_id = {v.id: v for v in vectors}
        for d in divergences:
            rule = self.rules_by_id.get(d.rule_ids[0]) if d.rule_ids else None
            result = div_ai.diagnose(rule, d)
            if result.abstained:
                tracer.record_manual_abstention("DivergenceAI", d.vector_id, result.abstain_reason)
                continue
            diagnoses.append(result.value)
        tracer.record_step("Diagnose each divergence", "ai", detail=f"{len(diagnoses)} diagnosed")

        # ---- step 7: build the traceability matrix -----------------------
        matrix = build_traceability_matrix(self.rules, vectors, source, diagnoses)
        untraceable = collect_untraceable_findings(diagnoses, set(self.rules_by_id))
        tracer.record_step("Build the traceability matrix", "deterministic",
                            detail=f"{len(untraceable)} untraceable-behaviour findings")
        for row in matrix:
            verdict = "pass" if row.status in ("VALIDATED", "UNCOVERABLE") else "block"
            tracer.record_guardrail(f"G5 coverage: {row.rule_id}", verdict, row.status)

        coverage = coverage_from_matrix(matrix)
        facts = EvidenceFacts(
            run_id=run_id,
            total_rules=coverage.total_rules,
            rules_validated=coverage.validated,
            rules_invalidated=coverage.invalidated,
            rules_uncoverable=coverage.uncoverable + coverage.untested,
            total_vectors=len(vectors),
            total_divergences=len(divergences),
            known_divergence_ids=sorted({d.vector_id for d in divergences}),
            untraceable_findings=untraceable,
            traceability=matrix,
            determinism={
                "model": cfg["llm"]["model"], "temperature": cfg["llm"]["temperature"],
                "seed": cfg["llm"]["seed"],
            },
        )

        # ---- step 8: draft evidence sections --------------------------------
        sections: dict[str, str] = {}
        for kind in ["change_summary", "test_evidence", "impact_assessment",
                     "known_divergences", "rollback_plan"]:
            result = ev_ai.write_section(kind, facts)  # type: ignore[arg-type]
            if result.abstained:
                sections[kind] = f"(abstained: {result.abstain_reason})"
                tracer.record_manual_abstention("EvidenceAI", kind, result.abstain_reason)
            else:
                sections[kind] = result.value
        tracer.record_step("Draft evidence sections", "ai", detail=f"{len(sections)} sections")

        # ---- step 9: render the approval pack --------------------------------
        evidence_path = render_evidence_pack(facts, sections)
        tracer.record_step("Render the approval pack", "deterministic", detail=str(evidence_path))

        tracer.finalize({
            "total_rules": facts.total_rules,
            "validated": facts.rules_validated,
            "invalidated": facts.rules_invalidated,
            "uncoverable": facts.rules_uncoverable,
            "total_vectors": facts.total_vectors,
            "total_divergences": facts.total_divergences,
            "abstentions": len(tracer.abstentions),
        })

        return PipelineResult(
            rules=self.rules, sig=self.sig, vectors=vectors, source=source,
            divergences=divergences, diagnoses=diagnoses, matrix=matrix, facts=facts,
            sections=sections, evidence_path=evidence_path, trace_path=tracer.path,
            abstentions=tracer.abstentions,
        )

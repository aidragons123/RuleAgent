"""
core/differential.py - PRE-BUILT.
Runs the COBOL oracle and the generated Python implementation over a
vector set and reports every divergence, with the exact triggering
input and both outputs. Pure-Python, deterministic, no model calls.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from .cobol_runner import run_oracle
from .models import DivergenceRecord, IOSignature, SourceFile, TestVector


def load_generated_module(source: SourceFile) -> ModuleType:
    """Loads the AI-generated SourceFile from its on-disk path as a
    live Python module so it can be called."""
    path = Path(source.path)
    spec = importlib.util.spec_from_file_location("generated_intcalc", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def run_generated(module: ModuleType, vector_input: dict[str, str]) -> dict[str, str]:
    if not hasattr(module, "compute"):
        raise AttributeError(
            "Generated module must expose compute(input: dict) -> dict per io_signature.yaml"
        )
    return module.compute(dict(vector_input))


def run_differential(
    vectors: list[TestVector], module: ModuleType, sig: IOSignature
) -> list[DivergenceRecord]:
    """Runs both implementations over every vector; returns one record
    per (vector, field) mismatch - not one per vector, so a vector that
    diverges on two fields produces two records."""
    divergences: list[DivergenceRecord] = []
    for v in vectors:
        expected = run_oracle(v.input, sig)
        try:
            actual = run_generated(module, v.input)
        except Exception as exc:  # generated code crashed - report every output field as divergent
            actual = {name: f"<EXCEPTION: {exc}>" for name in sig.output_names()}
        for name in sig.output_names():
            exp_val = str(expected.get(name, "<MISSING>"))
            act_val = str(actual.get(name, "<MISSING>"))
            if exp_val != act_val:
                divergences.append(DivergenceRecord(
                    vector_id=v.id,
                    rule_ids=v.rule_ids,
                    field=name,
                    expected=exp_val,
                    actual=act_val,
                    cobol_output=expected,
                    python_output=actual,
                    input=v.input,
                ))
    return divergences

"""
core/differential.py - PRE-BUILT.
Runs the COBOL oracle and the generated "modern" implementation over a
vector set and reports every divergence, with the exact triggering
input and both outputs. Pure-Python orchestration, deterministic, no
model calls. The generated implementation can be either language:

  - a Java source file (generated/GeneratedIntcalc.java, the default) -
    compiled with javac and run as a subprocess per vector, over the
    exact same pipe-delimited wire protocol as the COBOL oracle (see
    core/java_runner.py and data/signature/io_signature.yaml).
  - a Python module (generated/intcalc_generated.py) - imported
    in-process and called directly. Kept for the original reference
    implementation / tests; ai/implementation.py's default output is
    now Java.

Either way, `load_generated(source, sig)` returns an object exposing
`.compute(input: dict) -> dict`, so everything below this line neither
knows nor cares which language actually produced the answer.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Protocol

from .cobol_runner import run_oracle
from .java_runner import JavaGeneratedModule, compile_java
from .models import DivergenceRecord, IOSignature, SourceFile, TestVector


class GeneratedModule(Protocol):
    def compute(self, input: dict[str, str]) -> dict[str, str]: ...


def load_generated_python_module(source: SourceFile) -> ModuleType:
    """Loads a Python SourceFile from its on-disk path as a live module
    so it can be called in-process. Only used when the AI-generated
    implementation is Python (source.path ends in .py)."""
    path = Path(source.path)
    spec = importlib.util.spec_from_file_location("generated_intcalc", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def load_generated(source: SourceFile, sig: IOSignature) -> GeneratedModule:
    """Dispatches on the generated source's file extension: compiles
    and wraps Java, or imports Python directly. Either branch returns
    something exposing the same `.compute(input) -> dict` surface."""
    if source.path.endswith(".java"):
        build_dir = compile_java(source)
        return JavaGeneratedModule(build_dir, sig)
    return load_generated_python_module(source)


# Kept for backwards compatibility with anything importing the old name.
load_generated_module = load_generated_python_module


def run_generated(module: GeneratedModule, vector_input: dict[str, str]) -> dict[str, str]:
    if not hasattr(module, "compute"):
        raise AttributeError(
            "Generated module must expose compute(input: dict) -> dict per io_signature.yaml"
        )
    return module.compute(dict(vector_input))


def run_differential(
    vectors: list[TestVector], module: GeneratedModule, sig: IOSignature
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
                    modern_output=actual,
                    input=v.input,
                ))
    return divergences

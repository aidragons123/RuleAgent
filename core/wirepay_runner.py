"""
core/wirepay_runner.py - PRE-BUILT.
Executes WIREPAY.cbl against an input vector via the shipped GnuCOBOL
runtime, and compiles/runs its AI-generated Java reimplementation -
mirroring core/cobol_runner.py + core/java_runner.py exactly, but
generalised (no field name is hardcoded) since WIREPAY's output fields
are named differently from INTCALC's.

core/cobol_runner.py's decode_output() and core/java_runner.py's
run_generated_java() cannot be reused as-is here: the former has an
INTCALC-specific normalisation line keyed on the literal field name
"interest", which would KeyError against WIREPAY's output signature.
This module is the same wire-protocol logic, generalised, so a second
legacy program can be validated without touching either write-locked,
INTCALC-specific file.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .models import IOSignature, SourceFile

REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY_DIR = REPO_ROOT / "data" / "src" / "legacy"
SOURCE = LEGACY_DIR / "WIREPAY.cbl"
BINARY = LEGACY_DIR / "wirepay"

GENERATED_DIR = REPO_ROOT / "generated"
BUILD_DIR = GENERATED_DIR / "javabuild_wirepay"
MAIN_CLASS = "GeneratedWirepay"


class WirepayRunnerError(RuntimeError):
    pass


# --------------------------------------------------------- wire protocol
def encode_input(vector_input: dict[str, str], sig: IOSignature) -> str:
    """Builds the fixed-width pipe-delimited line WIREPAY.cbl expects -
    identical convention to core/cobol_runner.py's encode_input()."""
    field_by_name = {f.name: f for f in sig.inputs}

    def pad(name: str) -> str:
        f = field_by_name[name]
        val = str(vector_input[name])
        return val.rjust(f.width) if f.type == "decimal" else val.ljust(f.width)[: f.width]

    parts = [pad(f.name) for f in sig.inputs]
    return sig.delimiter.join(parts)


def decode_output(line: str, sig: IOSignature) -> dict[str, str]:
    """Same shape as core/cobol_runner.py's decode_output(), minus the
    INTCALC-specific "interest" normalisation - every WIREPAY field is
    handled generically."""
    tokens = [t.strip() for t in line.strip().split(sig.delimiter)]
    names = sig.output_names()
    if len(tokens) != len(names):
        raise WirepayRunnerError(
            f"Oracle/generated output has {len(tokens)} fields, expected {len(names)}: {line!r}"
        )
    return dict(zip(names, tokens))


# ----------------------------------------------------------------- COBOL
def ensure_compiled() -> Path:
    """Compiles the WIREPAY oracle once if the binary is missing or stale."""
    if BINARY.exists() and BINARY.stat().st_mtime >= SOURCE.stat().st_mtime:
        return BINARY
    proc = subprocess.run(
        ["cobc", "-x", "-I", str(LEGACY_DIR), "-o", str(BINARY), str(SOURCE)],
        cwd=LEGACY_DIR, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise WirepayRunnerError(
            f"GnuCOBOL compile failed:\n{proc.stdout}\n{proc.stderr}\n"
            f"Is GnuCOBOL installed? Try: apt-get install gnucobol"
        )
    return BINARY


def run_oracle(vector_input: dict[str, str], sig: IOSignature) -> dict[str, str]:
    """Runs the compiled WIREPAY oracle once and returns the decoded,
    golden output dict - the only function allowed to be the source of
    an "expected" value for WIREPAY, exactly as core/cobol_runner.py's
    run_oracle() is for INTCALC."""
    binary = ensure_compiled()
    line = encode_input(vector_input, sig)
    proc = subprocess.run([str(binary)], input=line + "\n", capture_output=True, text=True)
    if proc.returncode != 0:
        raise WirepayRunnerError(f"Oracle run failed for input {line!r}:\n{proc.stderr}")
    return decode_output(proc.stdout.strip().splitlines()[-1], sig)


# ------------------------------------------------------------------ Java
def compile_java(source: SourceFile) -> Path:
    java_file = REPO_ROOT / source.path
    java_file.parent.mkdir(parents=True, exist_ok=True)
    java_file.write_text(source.content)

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["javac", "-d", str(BUILD_DIR), str(java_file)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise WirepayRunnerError(
            f"javac compile failed for {java_file}:\n{proc.stdout}\n{proc.stderr}\n"
            f"Is a JDK installed? Try: apt-get install default-jdk"
        )
    return BUILD_DIR


def run_generated_java(build_dir: Path, vector_input: dict[str, str], sig: IOSignature) -> dict[str, str]:
    line = encode_input(vector_input, sig)
    proc = subprocess.run(
        ["java", "-cp", str(build_dir), MAIN_CLASS],
        input=line + "\n", capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise WirepayRunnerError(f"java run failed for input {line!r}:\n{proc.stderr}")
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    if not lines:
        raise WirepayRunnerError(f"java produced no output for input {line!r}. stderr:\n{proc.stderr}")
    return decode_output(lines[-1], sig)


class WirepayGeneratedModule:
    """Same `.compute(input) -> dict` surface as core/java_runner.py's
    JavaGeneratedModule, backed by the WIREPAY-specific runner above."""

    def __init__(self, build_dir: Path, sig: IOSignature):
        self.build_dir = build_dir
        self.sig = sig

    def compute(self, input_dict: dict[str, str]) -> dict[str, str]:
        return run_generated_java(self.build_dir, input_dict, self.sig)


def load_generated(source: SourceFile, sig: IOSignature) -> WirepayGeneratedModule:
    build_dir = compile_java(source)
    return WirepayGeneratedModule(build_dir, sig)


# ------------------------------------------------------------- differential
def run_differential(vectors, module: WirepayGeneratedModule, sig: IOSignature) -> list:
    """Same logic as core/differential.py's run_differential(), pointed
    at WIREPAY's own oracle instead of INTCALC's - one DivergenceRecord
    per (vector, field) mismatch."""
    from .models import DivergenceRecord

    divergences: list[DivergenceRecord] = []
    for v in vectors:
        expected = run_oracle(v.input, sig)
        try:
            actual = module.compute(v.input)
        except Exception as exc:
            actual = {name: f"<EXCEPTION: {exc}>" for name in sig.output_names()}
        for name in sig.output_names():
            exp_val = str(expected.get(name, "<MISSING>"))
            act_val = str(actual.get(name, "<MISSING>"))
            if exp_val != act_val:
                divergences.append(DivergenceRecord(
                    vector_id=v.id, rule_ids=v.rule_ids, field=name,
                    expected=exp_val, actual=act_val,
                    cobol_output=expected, modern_output=actual, input=v.input,
                ))
    return divergences

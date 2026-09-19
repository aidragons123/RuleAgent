"""
core/java_runner.py - PRE-BUILT.
Compiles and runs the AI-generated Java reimplementation, using the
EXACT same pipe-delimited wire protocol as core/cobol_runner.py (see
data/signature/io_signature.yaml) - so the generated "modern" code is
executed the same way the real oracle is: compiled once, then invoked
as a subprocess per vector, never imported in-process. This keeps the
generated Java honest the same way the generated Python was: nothing
here reaches into it, it only talks to it over the documented wire
line, exactly like a real modernised service would sit behind an API
in front of the legacy system it replaces.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .cobol_runner import decode_output, encode_input
from .models import IOSignature, SourceFile

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATED_DIR = REPO_ROOT / "generated"
BUILD_DIR = GENERATED_DIR / "javabuild"
MAIN_CLASS = "GeneratedIntcalc"


class JavaRunnerError(RuntimeError):
    pass


def compile_java(source: SourceFile) -> Path:
    """Writes the AI-generated Java source to disk and compiles it with
    javac. Recompiles every call (the source is small; correctness over
    micro-caching, and it keeps a bug-injected variant from ever being
    served from a stale .class file)."""
    java_file = REPO_ROOT / source.path
    java_file.parent.mkdir(parents=True, exist_ok=True)
    java_file.write_text(source.content)

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["javac", "-d", str(BUILD_DIR), str(java_file)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise JavaRunnerError(
            f"javac compile failed for {java_file}:\n{proc.stdout}\n{proc.stderr}\n"
            f"Is a JDK installed? Try: apt-get install default-jdk"
        )
    return BUILD_DIR


def run_generated_java(build_dir: Path, vector_input: dict[str, str], sig: IOSignature) -> dict[str, str]:
    """Runs the compiled Java class on one vector using the same
    pipe-delimited line protocol as the COBOL oracle, and returns the
    decoded output dict."""
    line = encode_input(vector_input, sig)
    proc = subprocess.run(
        ["java", "-cp", str(build_dir), MAIN_CLASS],
        input=line + "\n", capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise JavaRunnerError(f"java run failed for input {line!r}:\n{proc.stderr}")
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    if not lines:
        raise JavaRunnerError(f"java produced no output for input {line!r}. stderr:\n{proc.stderr}")
    return decode_output(lines[-1], sig)


class JavaGeneratedModule:
    """A drop-in stand-in for the Python `module` object that
    core/differential.py already knows how to call: exposes the same
    `.compute(input: dict) -> dict` surface, backed by a real compiled
    Java class instead of an in-process import."""

    def __init__(self, build_dir: Path, sig: IOSignature):
        self.build_dir = build_dir
        self.sig = sig

    def compute(self, input_dict: dict[str, str]) -> dict[str, str]:
        return run_generated_java(self.build_dir, input_dict, self.sig)

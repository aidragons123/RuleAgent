"""
core/cobol_runner.py - PRE-BUILT.
Executes INTCALC.cbl against an input vector via the shipped GnuCOBOL
runtime (pre-installed) and returns the golden output. This is THE
ORACLE - the only source of expected values anywhere in this project.
Guardrail G1 exists precisely so nothing else is ever used instead.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .models import IOSignature

REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY_DIR = REPO_ROOT / "data" / "src" / "legacy"
SOURCE = LEGACY_DIR / "INTCALC.cbl"
BINARY = LEGACY_DIR / "intcalc"


class CobolRunnerError(RuntimeError):
    pass


def ensure_compiled() -> Path:
    """Compiles the oracle once if the binary is missing or stale."""
    if BINARY.exists() and BINARY.stat().st_mtime >= SOURCE.stat().st_mtime:
        return BINARY
    proc = subprocess.run(
        ["cobc", "-x", "-I", str(LEGACY_DIR), "-o", str(BINARY), str(SOURCE)],
        cwd=LEGACY_DIR, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise CobolRunnerError(
            f"GnuCOBOL compile failed:\n{proc.stdout}\n{proc.stderr}\n"
            f"Is GnuCOBOL installed? Try: apt-get install gnucobol"
        )
    return BINARY


def encode_input(vector_input: dict[str, str], sig: IOSignature) -> str:
    """Builds the fixed-width pipe-delimited line INTCALC.cbl expects."""
    field_by_name = {f.name: f for f in sig.inputs}

    def pad(name: str) -> str:
        f = field_by_name[name]
        val = str(vector_input[name])
        return val.rjust(f.width) if f.type == "decimal" else val.ljust(f.width)[: f.width]

    parts = [pad(f.name) for f in sig.inputs]
    return sig.delimiter.join(parts)


def decode_output(line: str, sig: IOSignature) -> dict[str, str]:
    tokens = [t.strip() for t in line.strip().split(sig.delimiter)]
    names = sig.output_names()
    if len(tokens) != len(names):
        raise CobolRunnerError(
            f"Oracle output has {len(tokens)} fields, expected {len(names)}: {line!r}"
        )
    out = dict(zip(names, tokens))
    # normalise: interest/adjustment come back as plain signed decimal strings
    if not out["interest"].startswith("-"):
        out["interest"] = out["interest"].lstrip()
    return out


def run_oracle(vector_input: dict[str, str], sig: IOSignature) -> dict[str, str]:
    """Runs the compiled COBOL oracle once and returns the decoded,
    golden output dict. This is the only function in the repo allowed
    to be the source of an "expected" value."""
    binary = ensure_compiled()
    line = encode_input(vector_input, sig)
    proc = subprocess.run([str(binary)], input=line + "\n", capture_output=True, text=True)
    if proc.returncode != 0:
        raise CobolRunnerError(f"Oracle run failed for input {line!r}:\n{proc.stderr}")
    return decode_output(proc.stdout.strip().splitlines()[-1], sig)

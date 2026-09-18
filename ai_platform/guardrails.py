"""
platform/guardrails.py (on disk: ai_platform/guardrails.py). PRE-BUILT.

The 6 guardrails from the use-case brief. 4 of the 6 are HARD: a
breach costs points, uncapped, and no accuracy gain earns it back.
"prompt says not to" is not a control and is not accepted as one -
these are checked in code, not left to prompt wording.

  G1 HARD  Never derive an expected value from generated code.
  G2 HARD  Never change a test to make the implementation pass.
  G3       Never claim equivalence.
  G4 HARD  Never implement undocumented behaviour silently.
  G5 HARD  Never mark a rule covered without a traceable test.
  G6       Evidence only from harness output.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_EQUIVALENCE_WORDS = re.compile(r"\bequivalent\b", re.IGNORECASE)


class GuardrailViolation(Exception):
    """Raised when a HARD guardrail would otherwise be breached."""


# --------------------------------------------------------------- G3 --
def _walk_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk_strings(v)
    elif hasattr(obj, "model_dump"):
        yield from _walk_strings(obj.model_dump())


def check_no_equivalence_claim(result) -> None:
    """G3: the word 'equivalent' is rejected outright, everywhere in
    an AIResult. Correct phrasing is 'no divergence found over N
    vectors', which is falsifiable; 'equivalent' is a claim about all
    inputs, and only finitely many were tested."""
    for text in _walk_strings(result):
        if FORBIDDEN_EQUIVALENCE_WORDS.search(text):
            raise GuardrailViolation(
                f'G3 breach: forbidden word "equivalent" found in AI output: {text!r}'
            )


# --------------------------------------------------------------- G1 --
def check_test_synthesis_has_no_implementation(ctx: dict) -> None:
    """G1: the context handed to TestSynthesisAI must never contain a
    generated implementation. Structural check, called at the pipeline
    call site as well as here so a future refactor can't quietly break it."""
    if "implementation" in ctx or "generated_source" in ctx or "expected" in ctx:
        raise GuardrailViolation(
            "G1 breach: test synthesis context must not include an implementation "
            "or expected output - expectations come only from core/cobol_runner.py."
        )


# --------------------------------------------------------------- G4 --
def check_no_silent_undocumented_behaviour(source: str, cited_rule_ids: set[str],
                                            all_rule_ids: set[str]) -> list[str]:
    """G4: returns a list of warnings (does not raise) when generated
    source cites a rule id that does not exist in validated_rules.yaml
    - i.e. it invented a rule to justify a branch. Actual undocumented
    COBOL behaviour (the cap) is caught by core/traceability.py via the
    differential run, not by scanning source text."""
    invented = sorted(cited_rule_ids - all_rule_ids)
    return [f"Generated source cites unknown rule id {rid!r}" for rid in invented]


# --------------------------------------------------------------- G5 --
def rule_is_traceably_covered(rule_id: str, vectors: list, code_citations: dict) -> bool:
    """G5: a rule counts as covered only if at least one test vector
    cites it AND at least one generated-code citation cites it. Line
    coverage is not rule coverage."""
    has_test = any(rule_id in v.rule_ids for v in vectors)
    has_code = any(rule_id in cites for cites in code_citations.values())
    return has_test and has_code


# --------------------------------------------------------------- G2 --
def compute_manifest(paths: list[Path]) -> dict[str, str]:
    manifest = {}
    for p in paths:
        if p.is_file():
            try:
                rel = str(p.relative_to(REPO_ROOT))
            except ValueError:
                rel = str(p)  # path outside the repo (e.g. a test's tmp_path)
            manifest[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return manifest


def write_manifest(manifest_path: Path, exclude_dirs: tuple[str, ...] = ("ai", ".git",
                    "traces", "out", "generated", "__pycache__", ".pytest_cache")) -> None:
    paths = []
    for p in REPO_ROOT.rglob("*"):
        if p.is_file() and not any(part in exclude_dirs for part in p.parts):
            if p.name == manifest_path.name:
                continue
            paths.append(p)
    manifest = compute_manifest(paths)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))


def verify_manifest(manifest_path: Path, exclude_dirs: tuple[str, ...] = ("ai", ".git",
                     "traces", "out", "generated", "__pycache__", ".pytest_cache")) -> list[str]:
    """G2 enforcement for `make verify`. Returns a list of violations
    (empty = clean). A non-empty list means the submission is not
    scored."""
    if not manifest_path.exists():
        return ["No manifest found - run `make freeze-manifest` once, before editing ai/."]
    stored = json.loads(manifest_path.read_text())
    violations = []
    seen = set()
    for rel, digest in stored.items():
        seen.add(rel)
        p = REPO_ROOT / rel
        if not p.exists():
            violations.append(f"DELETED: {rel}")
            continue
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        if actual != digest:
            violations.append(f"MODIFIED: {rel}")
    for p in REPO_ROOT.rglob("*"):
        if p.is_file() and not any(part in exclude_dirs for part in p.parts) \
                and p.name != manifest_path.name:
            rel = str(p.relative_to(REPO_ROOT))
            if rel not in seen:
                violations.append(f"ADDED: {rel}")
    return violations

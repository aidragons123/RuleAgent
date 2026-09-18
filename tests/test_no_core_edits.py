"""tests/test_no_core_edits.py - PRE-BUILT, do not modify.
Checksums every file outside ai/. This is also what `make verify`
runs directly (see Makefile) - this test just makes it visible to
`make test` too."""
from pathlib import Path

from ai_platform.guardrails import verify_manifest

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / ".manifest.json"


def test_nothing_outside_ai_has_been_modified():
    violations = verify_manifest(MANIFEST_PATH)
    assert not violations, (
        "The repository is write-locked outside ai/. Violations:\n" + "\n".join(violations)
    )

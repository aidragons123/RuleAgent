"""
core/rules_loader.py - PRE-BUILT.
Loads and validates the 24 SME-approved rules and the IO signature,
including COMP-3 scales.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .models import BusinessRule, IOField, IOSignature

REPO_ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = REPO_ROOT / "data" / "rules" / "validated_rules.yaml"
SIGNATURE_PATH = REPO_ROOT / "data" / "signature" / "io_signature.yaml"


def load_rules(path: Path = RULES_PATH) -> list[BusinessRule]:
    data = yaml.safe_load(path.read_text())
    return [BusinessRule(**r) for r in data["rules"]]


def load_signature(path: Path = SIGNATURE_PATH) -> IOSignature:
    data = yaml.safe_load(path.read_text())
    return IOSignature(
        delimiter=data["protocol"]["delimiter"],
        encoding=data["protocol"]["encoding"],
        inputs=[IOField(**f) for f in data["inputs"]],
        outputs=[IOField(**f) for f in data["outputs"]],
    )


def rules_by_id(rules: list[BusinessRule] | None = None) -> dict[str, BusinessRule]:
    rules = rules or load_rules()
    return {r.id: r for r in rules}

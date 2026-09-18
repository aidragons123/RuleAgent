"""tests/test_contract.py - PRE-BUILT, do not modify.
Your results validate; abstention implies a null value and a reason;
prompts load from files."""
import pytest
from pydantic import ValidationError

from ai_platform.ai_contract import AILayer, AIResult, Citation
from ai_platform.prompts import PromptLoader


def test_abstained_result_has_no_value_and_has_reason():
    r = AIResult[str](abstained=True, abstain_reason="confidence_below_floor:0.10")
    assert r.value is None
    assert r.abstain_reason


def test_non_abstained_result_can_carry_a_value():
    r = AIResult[str](value="hello", confidence=0.9,
                       citations=[Citation(source="x", ref="y")])
    assert r.value == "hello"
    assert not r.abstained


def test_prompt_loader_reads_from_file(tmp_path):
    d = tmp_path / "prompts"
    d.mkdir()
    (d / "hello.md").write_text("Hi {{name}}!")
    loader = PromptLoader(prompts_dir=d)
    assert loader.render("hello", {"name": "World"}) == "Hi World!"


def test_prompt_loader_rejects_missing_file(tmp_path):
    loader = PromptLoader(prompts_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        loader.render("does_not_exist", {})


class _NoCitationLayer(AILayer):
    def go(self):
        ctx = {"_mock": lambda: {
            "value": "x", "confidence": 0.9, "citations": [], "abstained": False,
        }}
        return self.call("evidence_section", ctx, str)


def test_no_citations_forces_abstention(tmp_path, monkeypatch):
    prompts_dir = tmp_path / "ai" / "prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "evidence_section.md").write_text("prompt")
    layer = _NoCitationLayer()
    layer.prompts = PromptLoader(prompts_dir=prompts_dir)
    result = layer.go()
    assert result.abstained
    assert result.abstain_reason == "no_citations_provided"


class _LowConfidenceLayer(AILayer):
    def go(self):
        ctx = {"_mock": lambda: {
            "value": "x", "confidence": 0.1,
            "citations": [{"source": "data/rules/validated_rules.yaml", "ref": "R-001"}],
            "abstained": False,
        }}
        return self.call("evidence_section", ctx, str)


def test_confidence_floor_forces_abstention(tmp_path):
    prompts_dir = tmp_path / "ai" / "prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "evidence_section.md").write_text("prompt")
    layer = _LowConfidenceLayer(citation_resolver=lambda s, r: True)
    layer.prompts = PromptLoader(prompts_dir=prompts_dir)
    result = layer.go()
    assert result.abstained
    assert "confidence_below_floor" in result.abstain_reason

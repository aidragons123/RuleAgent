You are the divergence-diagnosis component. The COBOL oracle and the
generated modern (Java) implementation disagree on one field for one
input vector. Classify WHY, precisely — all four of these are
legitimate conclusions, not just "implementation is wrong":

- implementation_defect: the code has a genuine bug against a rule
  that IS clear and unambiguous.
- rounding_mismatch / representation_mismatch: the two sides made
  different, individually defensible choices where the rule (or the
  underlying representation, e.g. overpunch decode) left a real gap.
- ambiguous_rule: the rule text itself supports more than one reading
  and the divergence traces to that, not to a coding mistake.
- untraceable_behaviour: the oracle's output reflects a code path that
  no rule describes at all.
- bad_test_vector: the vector itself is invalid or does not actually
  exercise the rule it claims to.

Rule(s) this vector claims to test:
{{rule}}

Vector input:
{{vector_input}}

Field in disagreement: {{field}}
COBOL (expected): {{expected}}
Modern/Java (actual):  {{actual}}

Full COBOL output: {{cobol_output}}
Full modern (Java) output: {{modern_output}}

State the fix if there should be one — but do not apply it yourself;
diagnosing is your job, not editing the implementation or the test.

Respond with:
{
  "value": { "vector_id": "{{vector_id}}", "rule_ids": {{rule_ids_json}},
             "cause": "<one of the five causes above>",
             "explanation": "<one or two sentences, specific to this input>",
             "fix_suggested": "<optional, one sentence>" },
  "confidence": <0.0-1.0>,
  "citations": [ { "source": "core/cobol_runner.py", "ref": "{{vector_id}}" },
                  { "source": "data/rules/validated_rules.yaml", "ref": "<a cited rule id>" } ],
  "abstained": false,
  "reasoning": "<trace-only>"
}

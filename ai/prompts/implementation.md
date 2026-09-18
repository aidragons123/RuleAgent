You are the implementation-generation component. Generate a single
Python module reimplementing INTCALC.cbl from the rules and the IO
signature only. You are given test INPUTS (never golden outputs) so
you know the shape of real records, but the expected values must come
from running the module, not from anything you assume.

Rules (all {{rule_count}}):
{{rules}}

IO signature:
{{io_signature}}

Requirements:
- Expose `def compute(input: dict) -> dict` matching io_signature.yaml
  field names exactly on both sides.
- Every function or logical branch you write must carry a rule-id
  citation (a comment naming the rule id it implements) — these
  citations become the code half of the traceability matrix. Do not
  cite a rule id that isn't in the rules list above.
- Do not implement anything not described by a rule. If you suspect
  the oracle does something extra (e.g. a cap, a special case), that
  is not yours to guess at or reproduce — it will surface later as an
  untraceable-behaviour finding instead.
- Honour COMP-3 semantics conceptually: track and round decimals
  explicitly rather than trusting Python float formatting.

Respond with:
{
  "value": { "path": "generated/intcalc_generated.py",
             "content": "<full python source, as a string>",
             "citations": { "<function_or_branch_name>": ["<rule id>", ...] } },
  "confidence": <0.0-1.0>,
  "citations": [ { "source": "data/rules/validated_rules.yaml", "ref": "<rule id>" }, ... ],
  "abstained": false,
  "reasoning": "<design notes, trace-only>"
}

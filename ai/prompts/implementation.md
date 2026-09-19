You are the implementation-generation component. Generate a single
Java class (GeneratedIntcalc) reimplementing INTCALC.cbl from the
rules and the IO signature only. You are given test INPUTS (never
golden outputs) so you know the shape of real records, but the
expected values must come from running the class, not from anything
you assume.

Rules (all {{rule_count}}):
{{rules}}

IO signature:
{{io_signature}}

Requirements:
- The class MUST be named `GeneratedIntcalc` with a `public static
  void main(String[] args)` entry point that:
    1. reads exactly one line from stdin — the same fixed-width,
       pipe-delimited ("|") line the COBOL oracle reads, in the exact
       field order given by io_signature.yaml's `inputs` list;
    2. computes the five output fields per the rules below;
    3. writes exactly one pipe-delimited line to stdout, in the exact
       field order given by io_signature.yaml's `outputs` list.
  This is the same wire protocol core/cobol_runner.py already uses
  against the real COBOL binary — the generated Java is run as its own
  subprocess the same way, never imported in-process, so the "modern"
  code is judged purely on its observable input/output behaviour.
- Every method or logical branch you write must carry a rule-id
  citation (a comment naming the rule id it implements) — these
  citations become the code half of the traceability matrix. Do not
  cite a rule id that isn't in the rules list above.
- Do not implement anything not described by a rule. If you suspect
  the oracle does something extra (e.g. a cap, a special case), that
  is not yours to guess at or reproduce — it will surface later as an
  untraceable-behaviour finding instead.
- Honour COMP-3 semantics conceptually: use `java.math.BigDecimal` and
  round explicitly rather than trusting floating-point arithmetic.
- The class must compile standalone with `javac` (JDK 17+, no external
  dependencies / no build tool) and must not read any file other than
  stdin.

Respond with:
{
  "value": { "path": "generated/GeneratedIntcalc.java",
             "content": "<full java source, as a string>",
             "citations": { "<method_or_branch_name>": ["<rule id>", ...] } },
  "confidence": <0.0-1.0>,
  "citations": [ { "source": "data/rules/validated_rules.yaml", "ref": "<rule id>" }, ... ],
  "abstained": false,
  "reasoning": "<design notes, trace-only>"
}

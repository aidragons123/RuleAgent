You are drafting ONE section of a change-approval evidence pack for a
bank's risk/approval board. Every sentence you write must be
supported by the facts object below — the renderer rejects any claim
it cannot tie back to harness output. Never write "equivalent"; write
"no divergence found over N vectors" and give N. State known
divergences and untraceable behaviour plainly; a board that trusts the
pack more because it says what it doesn't know is the point of this
exercise.

Section to draft: {{kind}}

Facts (the ONLY source of truth for this section):
{{facts}}

Respond with:
{
  "value": "<the section's prose, plain text, a few sentences to a short paragraph>",
  "confidence": <0.0-1.0>,
  "citations": [ { "source": "eval/score.py", "ref": "run_summary" } ],
  "abstained": false,
  "reasoning": "<trace-only>"
}

# UC-04 · From Validated Rules to Tested Code

An AI-assisted COBOL-modernisation pipeline: given a legacy COBOL module and
a list of SME-validated business rules, an AI layer synthesises test
vectors from the rules, generates a Python reimplementation, diffs it
against the real COBOL oracle, diagnoses every divergence by cause, and
renders a change-approval evidence pack — a **rule-by-rule validation
report** showing exactly which rules are flawless and which are flawed,
and on which side (the code, or the rule text itself).

Runs end to end with **zero API keys** (a deterministic offline "mock LLM"
backend is the default), and is pluggable to a real Claude call with one
config line. GnuCOBOL is the only non-Python dependency, and it's a one-line
install.

## Quickstart

```bash
git clone <this repo>
cd uc04-ai-assisted-delivery

# GnuCOBOL - the oracle needs this to compile/run the real COBOL module
apt-get install -y gnucobol         # macOS: brew install gnu-cobol

pip install -r requirements.txt

make test        # 66 pytest tests, pre-built, scoring gate
make verify       # confirms nothing outside ai/ was modified
make demo         # THE ONE COMMAND — happy flow, then two negative
                  # scenarios, then opens the HTML trace
make score        # held-back evaluation set, pass rate + rule coverage
make score REPEAT=2   # + run-to-run variance report
make ui           # Streamlit UI over the same pipeline
```

Open in VS Code with `code .` — it's a plain Python project, no special
tooling required beyond the above.

## What you get out of the box

Running `make demo` (or the Streamlit UI's "Full run") produces, for every
one of the 24 validated rules, a clear verdict:

| Status | Meaning |
|---|---|
| ✅ **VALIDATED** | flawless — zero divergence from the COBOL oracle across every cited test |
| ❌ **INVALIDATED — implementation defect** | the code is genuinely wrong against a clear rule |
| ⚠️ **INVALIDATED — rounding/representation** | a real, individually-defensible disagreement where the rule left a gap (e.g. a half-cent tie-break) |
| ⚠️ **INVALIDATED — ambiguous rule text** | the divergence traces to the rule's own wording, not a coding mistake |
| ◻️ **UNCOVERABLE / UNTESTED** | the rule's claim isn't independently observable from this module's output, and the AI correctly declined to fabricate a test for it |

A sample run: **9 validated, 7 invalidated (4 ambiguous-rule, 3
rounding/representation), 8 uncoverable/untested**, out of 24 — plus one
**untraceable-behaviour finding**: an interest cap the COBOL applies that no
rule describes at all. Every number here is generated live from the actual
run, not scripted.

## Architecture

```
uc04-ai-assisted-delivery/
├── data/                    PRE-BUILT, read-only test data
│   ├── src/legacy/          INTCALC.cbl (the oracle) + ACCTREC.cpy
│   ├── rules/               validated_rules.yaml — 24 SME-approved rules
│   ├── signature/           io_signature.yaml — the input/output contract
│   └── vectors/             seed (30, easy) + heldback (200, pathological)
├── core/                    PRE-BUILT, deterministic pipeline
│   ├── models.py            shared pydantic data model
│   ├── rules_loader.py      loads rules + IO signature
│   ├── cobol_runner.py      compiles & runs INTCALC.cbl — THE ORACLE
│   ├── differential.py      runs oracle vs generated code, finds divergences
│   ├── traceability.py      builds the rule → test → code matrix
│   ├── harness.py           timing / coverage bookkeeping
│   ├── evidence_render.py   renders out/evidence_pack.html
│   └── pipeline.py          wires all nine steps in order
├── ai_platform/             PRE-BUILT platform (see naming note below)
│   ├── ai_contract.py       Citation / AIResult / AILayer.call() — the 8 enforced rules
│   ├── guardrails.py        the 6 guardrails (4 hard)
│   ├── tracer.py            writes the self-contained HTML trace
│   ├── llm_client.py        mock (offline, deterministic) / real (Anthropic) backend
│   └── config.yaml          thresholds, budgets, LLM mode
├── ai/                      *** the AI layer — the actual judgement calls ***
│   ├── test_synthesis.py    boundary-aware vector synthesis per rule
│   ├── implementation.py    generates the Python reimplementation
│   ├── divergence.py        classifies why oracle and code disagree
│   ├── evidence.py          drafts the change-approval pack's prose
│   ├── prompts/*.md         the actual prompts (sent verbatim in "real" LLM mode)
│   └── _mock_backend.py     shared helper math for the offline mock backend only
├── tests/                   PRE-BUILT pytest suite (scoring gate)
├── eval/score.py            held-back scoring + variance report
├── generated/               AI-generated Python module lands here
├── traces/                  one HTML trace per run
├── out/                     evidence_pack.html + score_report.json
├── run.py                   CLI (demo / case / trace / baseline)
├── streamlit_app.py         interactive UI over the same pipeline
└── Makefile
```

### A note on the `platform/` folder name

The brief this project is based on names the pre-built platform folder
`platform/`. On disk here it's `ai_platform/` instead — a literal `platform/`
package at the repo root shadows Python's own standard-library `platform`
module the instant the repo root is on `sys.path`, which silently breaks
`uuid`, `pytest`, `streamlit` and others that import it internally. Every
other path in the tree above matches the brief exactly; this is the one
deliberate rename, made for the project to actually run reliably rather than
work only by accident of import order.

## The pipeline, in order

1. **Load rules + IO signature** (`core/rules_loader.py`)
2. **Synthesise test vectors per rule** (`ai/test_synthesis.py`) — given the
   rule and the signature only, never an implementation (guardrail G1)
3. **Golden output** comes from `core/cobol_runner.py` running the real,
   compiled COBOL — invoked lazily per vector, never assumed
4. **Generate the implementation** (`ai/implementation.py`) — from rules +
   signature only, never from golden outputs
5. **Run both, find divergences** (`core/differential.py`)
6. **Diagnose each divergence** (`ai/divergence.py`) — one of five causes:
   implementation defect, rounding/representation mismatch, ambiguous rule,
   untraceable behaviour, or a bad test vector — never a single
   undifferentiated "failed"
7. **Build the traceability matrix** (`core/traceability.py`) — a rule counts
   as covered only with both a citing test *and* a citing code path (G5)
8. **Draft evidence sections** (`ai/evidence.py`) — every sentence must
   resolve to a fact; the word "equivalent" is rejected outright (G3)
9. **Render the approval pack** (`core/evidence_render.py`) →
   `out/evidence_pack.html`

## The guardrails (`ai_platform/guardrails.py`)

4 of 6 are hard-enforced in code, not left to prompt wording:

- **G1 (hard)** test synthesis never sees an implementation or expected value
- **G2 (hard)** `make verify` checksums everything outside `ai/`
- **G3** the word "equivalent" is rejected everywhere in AI output
- **G4 (hard)** undocumented COBOL behaviour (the interest cap) is reported
  as an untraceable-behaviour finding, never silently reproduced
- **G5 (hard)** a rule is "covered" only with both a citing test and a
  citing code path
- **G6** evidence sections only ever draw from the structured `EvidenceFacts`
  object, checked both at generation time and again at render time

## Plugging in a real LLM

Everything above runs against a deterministic offline "mock" backend by
default (`ai_platform/config.yaml`: `llm.mode: mock`) so the whole thing is
reproducible and free to demo. To use a real model instead:

```yaml
# ai_platform/config.yaml
llm:
  mode: real
  model: "claude-sonnet-5"
```

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-...
make demo
```

In real mode, the prompts in `ai/prompts/*.md` are rendered and sent
verbatim; the model's JSON response is validated against the same
`AIResult[T]` schema either way. If the key or package is missing, it falls
back to mock mode with a warning rather than breaking the run.

## The seeded pathologies

The COBOL oracle (`data/src/legacy/INTCALC.cbl`) deliberately contains:

1. **COMP-3 half-cent rounding** — `ROUNDED` resolves ties away from zero;
   a natural Python reading (banker's rounding) does not.
2. **Signed zoned-decimal overpunch** on the adjustment field — decoded
   correctly here (fully validated; see `io_signature.yaml`).
3. **Two-digit year window**, pivot at 50 — decoded correctly here too.
4. **A genuinely ambiguous tier boundary** — "up to 1,000.00" is read
   inclusively by the generated code and exclusively by the COBOL.
5. **One undocumented branch** (an interest cap) that no rule describes at
   all — the traceability checker finds it; the implementation correctly
   never guesses at it.
6. **A mutually-exclusive rule pair** (R-023/R-024) that cannot both be
   confirmed by a single vector, and whose claimed effect isn't observable
   in this module's output at all — correctly left untested rather than
   faked.

## Extending it

- Add a rule → `data/rules/validated_rules.yaml`; the pipeline picks it up
  automatically (synthesise a vector for it or explain why you can't).
- Regenerate the vector files: `python data/vectors/_generate.py`.
- The generated implementation always lands at
  `generated/intcalc_generated.py` — read it after any run to see exactly
  what the AI layer wrote and why (every branch carries a rule-id comment).

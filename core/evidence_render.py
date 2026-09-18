"""
core/evidence_render.py - PRE-BUILT.
Renders the change-approval evidence pack from structured harness
output into out/evidence_pack.html. Refuses to render any AI-authored
section that still contains the word "equivalent" (G3) - belt and
suspenders on top of the check already done in ai_platform.guardrails.

This is also where the rule-by-rule VALIDATION REPORT lives: every
rule, its status (VALIDATED / INVALIDATED / UNCOVERABLE), which side
the flaw is on when there is one, and the evidence for it.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from ai_platform.guardrails import FORBIDDEN_EQUIVALENCE_WORDS, GuardrailViolation

from .models import EvidenceFacts, SectionKind

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_ROOT / "out" / "evidence_pack.html"

STATUS_LABEL = {
    "VALIDATED": ("VALIDATED — flawless", "ok"),
    "INVALIDATED_DEFECT": ("INVALIDATED — implementation defect", "bad"),
    "INVALIDATED_ROUNDING": ("INVALIDATED — rounding/representation mismatch", "warn"),
    "INVALIDATED_AMBIGUOUS": ("INVALIDATED — ambiguous rule text", "warn"),
    "UNCOVERABLE": ("UNCOVERABLE — not independently testable", "muted"),
    "UNTESTED": ("UNTESTED", "muted"),
}
FLAW_SIDE_LABEL = {
    "none": "—", "code": "code", "rule": "rule text", "n/a": "n/a",
}


def _esc(x) -> str:
    return html.escape(str(x))


def _check_section_text(kind: SectionKind, text: str) -> None:
    if FORBIDDEN_EQUIVALENCE_WORDS.search(text):
        raise GuardrailViolation(
            f"G3 breach at render time: section {kind!r} still contains 'equivalent'."
        )


def render_evidence_pack(
    facts: EvidenceFacts, sections: dict[str, str], out_path: Path = OUT_PATH
) -> Path:
    for kind, text in sections.items():
        _check_section_text(kind, text)  # type: ignore[arg-type]

    validated = [r for r in facts.traceability if r.status == "VALIDATED"]
    invalidated = [r for r in facts.traceability if r.status.startswith("INVALIDATED")]
    uncoverable = [r for r in facts.traceability if r.status in ("UNCOVERABLE", "UNTESTED")]

    def rule_rows(rows) -> str:
        out = []
        for r in rows:
            label, css = STATUS_LABEL.get(r.status, (r.status, "muted"))
            diag_html = ""
            for d in r.diagnoses:
                diag_html += (
                    f"<div class='diag'><b>{_esc(d.vector_id)}</b> "
                    f"({_esc(d.cause)}): {_esc(d.explanation)}</div>"
                )
            out.append(
                f"<tr class='{css}'>"
                f"<td>{_esc(r.rule_id)}</td>"
                f"<td>{_esc(r.statement)}</td>"
                f"<td class='status'>{_esc(label)}</td>"
                f"<td>{_esc(FLAW_SIDE_LABEL.get(r.flaw_side, r.flaw_side))}</td>"
                f"<td>{_esc(', '.join(r.tests) or '—')}</td>"
                f"<td>{_esc(', '.join(r.code_citations) or '—')}</td>"
                f"<td>{diag_html or '—'}</td>"
                f"</tr>"
            )
        return "".join(out)

    untraceable_html = "".join(
        f"<li><b>{_esc(f.id)}</b>: {_esc(f.description)} "
        f"(triggering vectors: {_esc(', '.join(f.triggering_vectors))})</li>"
        for f in facts.untraceable_findings
    ) or "<li><i>None found.</i></li>"

    section_html = "".join(
        f"<h3>{_esc(kind.replace('_', ' ').title())}</h3><p>{_esc(text)}</p>"
        for kind, text in sections.items()
    )

    body = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>UC-04 change-approval evidence pack</title>
<style>
body {{ font-family: -apple-system, Segoe UI, sans-serif; margin: 2rem; color:#1a1a1a; }}
h1 {{ font-size: 1.4rem; }}
h2 {{ margin-top: 2rem; border-bottom: 1px solid #ddd; padding-bottom: .25rem; }}
.stat-row {{ display:flex; gap:1.5rem; margin: 1rem 0; }}
.stat {{ padding: .75rem 1.25rem; border-radius: 8px; font-weight: 600; }}
.stat.ok {{ background:#e6f6e6; color:#1a7a1a; }}
.stat.bad {{ background:#fdeaea; color:#b00020; }}
.stat.warn {{ background:#fff6e0; color:#946200; }}
.stat.muted {{ background:#f0f0f0; color:#555; }}
table {{ border-collapse: collapse; width: 100%; margin-top: .5rem; font-size:.85rem; }}
td, th {{ border: 1px solid #ddd; padding: .4rem .5rem; text-align:left; vertical-align: top; }}
tr.ok td.status {{ color:#1a7a1a; font-weight:600; }}
tr.bad td.status {{ color:#b00020; font-weight:600; }}
tr.warn td.status {{ color:#946200; font-weight:600; }}
tr.muted td.status {{ color:#777; }}
.diag {{ font-size:.8rem; margin-bottom:.25rem; }}
</style></head>
<body>
<h1>UC-04 &middot; Change-approval evidence pack</h1>
<p>Run <code>{_esc(facts.run_id)}</code></p>

<div class="stat-row">
  <div class="stat ok">{len(validated)} validated (flawless)</div>
  <div class="stat bad">{len(invalidated)} invalidated (flaw found)</div>
  <div class="stat muted">{len(uncoverable)} uncoverable / untested</div>
  <div class="stat warn">{facts.total_divergences} divergences over {facts.total_vectors} vectors</div>
</div>

{section_html}

<h2>Rule validation report — all {facts.total_rules} rules</h2>
<table>
<tr><th>Rule</th><th>Statement</th><th>Status</th><th>Flaw side</th>
<th>Citing tests</th><th>Citing code</th><th>Diagnosis</th></tr>
{rule_rows(facts.traceability)}
</table>

<h2>Untraceable behaviour findings</h2>
<p>Code paths in the oracle's output that no rule in
<code>data/rules/validated_rules.yaml</code> describes. These are
reported, not silently implemented (guardrail G4).</p>
<ul>{untraceable_html}</ul>

<h2>Determinism</h2>
<pre>{_esc(facts.determinism)}</pre>

</body></html>"""

    out_path.parent.mkdir(exist_ok=True, parents=True)
    out_path.write_text(body)
    return out_path

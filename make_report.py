"""
make_report.py - runs every UI scope and writes one consolidated HTML report.

Drives the real Streamlit app (via streamlit.testing) rather than calling
core.pipeline directly, so the report can never drift from what the UI
shows: same scopes, same bug injection, same scoped traceability matrix.

Usage (needs the GnuCOBOL environment, exactly like run_ui.cmd):
    run_report.cmd
    ...or: python make_report.py

Output: out/pipeline_report.html
"""
from __future__ import annotations

import datetime as dt
import html
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
OUT = REPO / "out" / "pipeline_report.html"
SCOPES = ["Full run", "Happy flow", "Rounding flaw", "Untraceable cap behaviour"]

# The project's status palette. These are STATUS colours (reserved), not a
# categorical series palette - so they are always rendered with their icon
# and label beside them. That secondary encoding is required, not optional:
# validated-green and defect-red are only ~4 Delta-E apart for deuteranopic
# readers, so colour alone would not distinguish "passed" from "failed".
STATUS = {
    "VALIDATED":             ("#0ca30c", "✅", "Validated — flawless"),
    "INVALIDATED_DEFECT":    ("#d03b3b", "❌", "Invalidated — implementation defect"),
    "INVALIDATED_ROUNDING":  ("#ec835a", "⚠️", "Invalidated — rounding / representation"),
    "INVALIDATED_AMBIGUOUS": ("#fab219", "❔", "Invalidated — ambiguous rule text"),
    "UNCOVERABLE":           ("#898781", "◻️", "Uncoverable"),
    "UNTESTED":              ("#898781", "◻️", "Untested"),
}
ORDER = list(STATUS)


def e(x) -> str:
    return html.escape(str(x))


def pct(n: int, total: int) -> float:
    return (n / total * 100) if total else 0.0


def tool_version(cmd: list[str], marker: str = "") -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        for line in (p.stdout + p.stderr).splitlines():
            if marker in line and line.strip():
                return line.strip()
        return (p.stdout + p.stderr).strip().splitlines()[0]
    except Exception as exc:
        return f"(unavailable: {exc})"


def collect() -> list[dict]:
    """Runs each scope through the actual app and harvests its result."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(REPO / "streamlit_app.py"), default_timeout=900)
    at.run()
    if at.exception:
        raise SystemExit(f"app failed to start: {at.exception[0].value}")

    runs = []
    for scope in SCOPES:
        print(f"  running scope: {scope} ...", flush=True)
        at.sidebar.selectbox[0].set_value(scope)
        at.sidebar.button[0].click().run()
        if at.exception:
            raise SystemExit(f"scope {scope!r} failed: {at.exception[0].value}")
        r = at.session_state["result"]
        f = r.facts
        # AppTest's session_state proxy has no .get(), only subscripting.
        try:
            bug = at.session_state["bug"]
        except Exception:
            bug = None
        diverged = {d.vector_id for d in r.divergences}
        runs.append({
            "scope": scope,
            "facts": f,
            "rows": list(f.traceability),
            "vectors": f.total_vectors,
            "divergences": f.total_divergences,
            "diverged_vectors": len(diverged),
            "matched_vectors": f.total_vectors - len(diverged),
            "untraceable": list(f.untraceable_findings),
            "samples": [d for d in r.divergences][:8],
            "trace": r.trace_path,
            "evidence": r.evidence_path,
            "bug": bug,
        })
    return runs


def stacked_bar(counts: dict[str, int], total: int) -> str:
    """Proportion bar. 2px surface gaps between segments; every segment is
    also spelled out in the legend beneath, so it is never colour-alone."""
    segs = "".join(
        f'<span class="seg" style="width:{pct(counts[s], total):.3f}%;'
        f'background:{STATUS[s][0]}" title="{e(STATUS[s][2])}: {counts[s]}"></span>'
        for s in ORDER if counts.get(s)
    )
    legend = "".join(
        f'<span class="lg"><span class="sw" style="background:{STATUS[s][0]}"></span>'
        f'{STATUS[s][1]} {e(STATUS[s][2])} '
        f'<b>{counts[s]}</b> <span class="mut">({pct(counts[s], total):.1f}%)</span></span>'
        for s in ORDER if counts.get(s)
    )
    return f'<div class="bar">{segs}</div><div class="legend">{legend}</div>'


def render(runs: list[dict]) -> str:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---- executive summary table across every scope
    summary_rows = ""
    for r in runs:
        f = r["facts"]
        judged = f.rules_validated + f.rules_invalidated
        summary_rows += (
            f"<tr><td><b>{e(r['scope'])}</b>"
            f"{'<br><span class=bugtag>flawed code injected</span>' if r['bug'] else ''}</td>"
            f"<td class=num>{f.total_rules}</td>"
            f"<td class=num><b>{pct(f.rules_validated, f.total_rules):.1f}%</b>"
            f"<div class=mut>{f.rules_validated} rules</div></td>"
            f"<td class=num>{pct(f.rules_invalidated, f.total_rules):.1f}%"
            f"<div class=mut>{f.rules_invalidated} rules</div></td>"
            f"<td class=num>{pct(f.rules_uncoverable, f.total_rules):.1f}%"
            f"<div class=mut>{f.rules_uncoverable} rules</div></td>"
            # No judgeable rule means there is no pass rate to report - "0%"
            # would read as "everything failed", which is not what happened.
            f"<td class=num>{f'{pct(f.rules_validated, judged):.1f}%' if judged else '—'}</td>"
            f"<td class=num>{r['vectors']}</td>"
            f"<td class=num>{pct(r['matched_vectors'], r['vectors']):.1f}%"
            f"<div class=mut>{r['matched_vectors']}/{r['vectors']}</div></td>"
            f"<td class=num>{r['divergences']}</td></tr>"
        )

    # ---- one detailed section per scope
    sections = ""
    for r in runs:
        facts = r["facts"]
        counts = {s: sum(1 for x in r["rows"] if x.status == s) for s in ORDER}
        judged = facts.rules_validated + facts.rules_invalidated

        tiles = (
            f'<div class="tiles">'
            f'<div class="tile" style="--a:{STATUS["VALIDATED"][0]}">'
            f'<div class="tl">Rules validated</div>'
            f'<div class="tv">{pct(facts.rules_validated, facts.total_rules):.1f}%</div>'
            f'<div class="ts">{facts.rules_validated} of {facts.total_rules} rules · '
            + (f'{pct(facts.rules_validated, judged):.1f}% of the {judged} judgeable'
               if judged else 'no rule here is independently judgeable')
            + '</div></div>'
            f'<div class="tile" style="--a:#7c56d6">'
            f'<div class="tl">Vectors matching the oracle</div>'
            f'<div class="tv">{pct(r["matched_vectors"], r["vectors"]):.1f}%</div>'
            f'<div class="ts">{r["matched_vectors"]} of {r["vectors"]} vectors · '
            f'{r["divergences"]} field-level divergences</div></div>'
            f'</div>'
        )

        rule_rows = "".join(
            f'<tr><td class=rid>{e(x.rule_id)}</td>'
            f'<td><span class="pill" style="border-color:{STATUS[x.status][0]}">'
            f'{STATUS[x.status][1]} {e(STATUS[x.status][2])}</span></td>'
            f'<td>{e(x.flaw_side)}</td><td class=num>{len(x.tests)}</td>'
            f'<td class=stmt>{e(x.statement)}</td></tr>'
            for x in r["rows"]
        )

        extra = ""
        if r["bug"]:
            extra += (
                f'<p class="callout bad"><b>Deliberately flawed code.</b> This scope '
                f'regenerated the Java with the <code>{e(r["bug"])}</code> defect, compiled '
                f'it, and ran it against the real COBOL oracle. The failures below are the '
                f'expected consequence — they demonstrate the checker catching a planted bug.</p>'
            )
        if r["untraceable"]:
            items = "".join(f"<li><b>{e(u.id)}</b> — {e(u.description)}</li>"
                            for u in r["untraceable"])
            extra += (
                f'<p class="callout warn"><b>{len(r["untraceable"])} untraceable-behaviour '
                f'finding(s).</b> The COBOL oracle does something no rule describes; the '
                f'generated code correctly declined to guess at it.</p><ul>{items}</ul>'
            )
        if r["samples"]:
            srows = "".join(
                f"<tr><td class=rid>{e(d.vector_id)}</td><td><code>{e(d.field)}</code></td>"
                f"<td class='num ok'>{e(d.expected)}</td><td class='num bad'>{e(d.actual)}</td></tr>"
                for d in r["samples"]
            )
            extra += (
                f'<h4>Sample divergences — COBOL oracle vs generated Java</h4>'
                f'<table class="grid"><thead><tr><th>Vector</th><th>Field</th>'
                f'<th class=num>COBOL (expected)</th><th class=num>Java (actual)</th>'
                f'</tr></thead><tbody>{srows}</tbody></table>'
            )

        sections += (
            f'<section><h2>{e(r["scope"])}</h2>{tiles}'
            f'{stacked_bar(counts, len(r["rows"]))}{extra}'
            f'<h4>Rule-by-rule verdict</h4>'
            f'<table class="grid"><thead><tr><th>Rule</th><th>Status</th><th>Flaw side</th>'
            f'<th class=num>Tests</th><th>Statement</th></tr></thead>'
            f'<tbody>{rule_rows}</tbody></table>'
            f'<p class="mut small">Trace: <code>{e(r["trace"])}</code></p></section>'
        )

    cobc = tool_version(["cobc", "--version"], "cobc")
    java = tool_version(["java", "-version"], "version")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CodeVerus — pipeline report</title>
<style>
  :root {{
    --ink:#14243a; --ink2:#48546a; --mut:#7c8798; --line:#e6e8ec;
    --bg:#f6f7f9; --card:#ffffff; --ok:#0ca30c; --bad:#d03b3b;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --ink:#e8ecf2; --ink2:#b3bccb; --mut:#8b96a7; --line:#2b3340;
             --bg:#161a20; --card:#1e232b; }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:2.2rem 1.2rem 4rem; background:var(--bg); color:var(--ink);
    font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif; }}
  .wrap {{ max-width:1080px; margin:0 auto; }}
  h1 {{ font-size:1.6rem; margin:0 0 .3rem; }}
  h2 {{ font-size:1.18rem; margin:0 0 .9rem; padding-bottom:.45rem;
        border-bottom:2px solid var(--line); }}
  h4 {{ font-size:.92rem; margin:1.4rem 0 .5rem; color:var(--ink2); }}
  section {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
    padding:1.3rem 1.4rem; margin-bottom:1.1rem; }}
  .sub {{ color:var(--mut); margin:0 0 1.4rem; font-size:.9rem; }}
  .tiles {{ display:flex; gap:.8rem; flex-wrap:wrap; margin-bottom:1rem; }}
  .tile {{ flex:1 1 240px; border:1px solid var(--line); border-top:4px solid var(--a);
    border-radius:12px; padding:.8rem 1rem; }}
  .tl {{ font-size:.72rem; letter-spacing:.07em; text-transform:uppercase; color:var(--mut);
    font-weight:700; }}
  .tv {{ font-size:2.3rem; font-weight:800; line-height:1.1; }}
  .ts {{ font-size:.82rem; color:var(--ink2); }}
  .bar {{ display:flex; height:22px; border-radius:6px; overflow:hidden; background:var(--line);
    margin:.2rem 0 .6rem; }}
  .seg {{ height:100%; border-right:2px solid var(--card); }}
  .seg:last-child {{ border-right:none; }}
  .legend {{ display:flex; flex-wrap:wrap; gap:.35rem 1.1rem; font-size:.84rem;
    color:var(--ink2); }}
  .lg {{ display:flex; align-items:center; gap:.35rem; }}
  .sw {{ width:11px; height:11px; border-radius:3px; display:inline-block; }}
  table.grid {{ border-collapse:collapse; width:100%; font-size:.86rem; }}
  table.grid th {{ text-align:left; color:var(--mut); font-size:.75rem; letter-spacing:.05em;
    text-transform:uppercase; border-bottom:2px solid var(--line); padding:.45rem .5rem; }}
  table.grid td {{ border-bottom:1px solid var(--line); padding:.45rem .5rem;
    vertical-align:top; }}
  .num {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
  td.ok {{ color:var(--ok); font-weight:700; }}
  td.bad {{ color:var(--bad); font-weight:700; }}
  .rid {{ font-weight:700; white-space:nowrap; }}
  .stmt {{ color:var(--ink2); }}
  .pill {{ display:inline-block; padding:.12rem .5rem; border:1.5px solid; border-radius:999px;
    font-size:.76rem; font-weight:600; white-space:nowrap; }}
  .mut {{ color:var(--mut); }} .small {{ font-size:.78rem; }}
  code {{ background:rgba(128,128,128,.14); padding:.05rem .32rem; border-radius:4px;
    font-size:.86em; }}
  .callout {{ border-left:4px solid var(--mut); padding:.6rem .9rem; border-radius:6px;
    background:rgba(128,128,128,.08); font-size:.88rem; }}
  .callout.bad {{ border-left-color:var(--bad); }}
  .callout.warn {{ border-left-color:#fab219; }}
  .bugtag {{ font-size:.72rem; color:var(--bad); font-weight:700; }}
  .env {{ font-size:.8rem; color:var(--mut); }}
  @media (max-width:640px) {{ .tiles {{ flex-direction:column; }}
    section {{ padding:1rem; }} body {{ padding:1.2rem .7rem 3rem; }} }}
</style></head><body><div class="wrap">

<h1>CodeVerus — pipeline report</h1>
<p class="sub">Legacy COBOL vs AI-generated Java, validated rule by rule against the
real compiled oracle. Generated {e(now)}.</p>

<section>
<h2>All scopes at a glance</h2>
<table class="grid"><thead><tr>
  <th>Scope</th><th class=num>Rules</th><th class=num>✅ Succeeded</th>
  <th class=num>❌ Failed</th><th class=num>◻️ Not testable</th>
  <th class=num>Pass rate*</th><th class=num>Vectors</th>
  <th class=num>Matched oracle</th><th class=num>Divergences</th>
</tr></thead><tbody>{summary_rows}</tbody></table>
<p class="mut small">*Pass rate counts only rules that can be judged — those with both a
citing test and a citing code path. Percentages in each row are of that row's scope,
not of all 24 rules; the scopes deliberately cover different rule subsets.</p>
</section>

{sections}

<section>
<h2>How this run was produced</h2>
<p class="env">
COBOL oracle: <code>{e(cobc)}</code><br>
Java: <code>{e(java)}</code><br>
AI layer: offline deterministic mock backend (<code>ai_platform/config.yaml</code>,
<code>llm.mode: mock</code>) — no API key, reproducible run to run.<br>
Every expected value above came from executing <code>data/src/legacy/INTCALC.cbl</code>
as a real compiled subprocess; every actual value from the compiled generated Java.
Nothing is simulated.
</p>
<p class="env">Evidence pack: <code>{e(runs[0]['evidence'])}</code><br>
Per-run HTML traces: <code>{e(REPO / 'traces')}</code></p>
</section>

</div></body></html>"""


def main() -> int:
    print("Running all scopes through the app ...", flush=True)
    runs = collect()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(runs), encoding="utf-8")
    print(f"\nReport written: {OUT}  ({OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

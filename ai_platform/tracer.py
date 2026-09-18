"""
platform/tracer.py (on disk: ai_platform/tracer.py). PRE-BUILT.

Tracing is pre-built and always on. ai/*.py writes no logging code -
the @traced decorator in ai_contract.py calls back into this module.

The moment a run starts, this creates traces/run_<timestamp>.html and
flushes it after every step, so it can be opened in a browser and
refreshed while the run is still going. Self-contained: no network,
no external assets, so it can be attached to an email or handed to a
judge as-is.
"""
from __future__ import annotations

import html
import json
import subprocess
import time
from pathlib import Path

TRACES_DIR = Path(__file__).resolve().parent.parent / "traces"


def _git_hash() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "no-git"


class Tracer:
    def __init__(self, case_ids: list[str], model: str, temperature: float, seed: int,
                 config_hash: str = ""):
        TRACES_DIR.mkdir(exist_ok=True, parents=True)
        ts = time.strftime("%Y%m%dT%H%M%S")
        self.path = TRACES_DIR / f"run_{ts}.html"
        self.header = {
            "case_ids": case_ids,
            "model": model,
            "temperature": temperature,
            "seed": seed,
            "config_hash": config_hash,
            "git_hash": _git_hash(),
            "started_at": ts,
        }
        self.steps: list[dict] = []
        self.ai_calls: list[dict] = []
        self.evidence_items: list[dict] = []
        self.guardrail_verdicts: list[dict] = []
        self.abstentions: list[dict] = []
        self.summary: dict = {}
        self._flush()

    # -------------------------------------------------------------- API
    def record_step(self, name: str, kind: str, elapsed_ms: int | None = None, detail: str = ""):
        self.steps.append({"name": name, "kind": kind, "elapsed_ms": elapsed_ms,
                            "detail": detail, "t": time.strftime("%H:%M:%S")})
        self._flush()

    def record_ai_call(self, step: dict, prompt_rendered: str, raw_response: str):
        entry = dict(step)
        entry["prompt_rendered"] = prompt_rendered
        entry["raw_response"] = raw_response
        self.ai_calls.append(entry)
        if entry.get("abstained"):
            self.abstentions.append({
                "layer": entry.get("layer"),
                "prompt_name": entry.get("prompt_name"),
                "reason": entry.get("abstain_reason"),
            })
        self._flush()

    def record_evidence_citation(self, source: str, ref: str, resolved: bool):
        self.evidence_items.append({"source": source, "ref": ref, "resolved": resolved})
        self._flush()

    def record_guardrail(self, name: str, verdict: str, reason: str = ""):
        self.guardrail_verdicts.append({"name": name, "verdict": verdict, "reason": reason})
        self._flush()

    def record_manual_abstention(self, who: str, rule_id: str, reason: str):
        self.abstentions.append({"layer": who, "prompt_name": rule_id, "reason": reason,
                                  "manual": True})
        self._flush()

    def finalize(self, summary: dict):
        self.summary = summary
        self._flush()

    # ----------------------------------------------------------- render
    def _flush(self):
        self.path.write_text(_render_html(self))


def _esc(x) -> str:
    return html.escape(str(x))


def _render_html(t: "Tracer") -> str:
    rows_steps = "".join(
        f"<tr><td>{_esc(s['t'])}</td><td>{_esc(s['name'])}</td>"
        f"<td class='{ 'ai' if s['kind']=='ai' else 'det' }'>{_esc(s['kind'])}</td>"
        f"<td>{_esc(s['elapsed_ms'] or '')}</td><td>{_esc(s['detail'])}</td></tr>"
        for s in t.steps
    )
    rows_ai = "".join(
        f"""<details><summary>{_esc(c['layer'])} · {_esc(c['prompt_name'])} · """
        f"""{'ABSTAINED: ' + _esc(c.get('abstain_reason')) if c.get('abstained') else 'confidence ' + _esc(round(c.get('confidence',0),2))} """
        f"""({_esc(c.get('elapsed_ms',0))}ms)</summary>"""
        f"<div class='callbox'><b>Prompt sent</b><pre>{_esc(c['prompt_rendered'])}</pre>"
        f"<b>Raw response</b><pre>{_esc(c['raw_response'])}</pre>"
        f"<b>Citations</b><pre>{_esc(json.dumps(c.get('citations', []), indent=2))}</pre></div></details>"
        for c in t.ai_calls
    )
    rows_guard = "".join(
        f"<tr><td>{_esc(g['name'])}</td>"
        f"<td class=\"{'pass' if g['verdict']=='pass' else 'block'}\">{_esc(g['verdict'])}</td>"
        f"<td>{_esc(g['reason'])}</td></tr>"
        for g in t.guardrail_verdicts
    )
    rows_abst = "".join(
        f"<tr><td>{_esc(a.get('layer'))}</td><td>{_esc(a.get('prompt_name'))}</td>"
        f"<td>{_esc(a.get('reason'))}</td></tr>"
        for a in t.abstentions
    )
    rows_evidence = "".join(
        f"<tr><td>{_esc(e['source'])}</td><td>{_esc(e['ref'])}</td>"
        f"<td class=\"{'pass' if e['resolved'] else 'block'}\">"
        f"{'resolved' if e['resolved'] else 'UNRESOLVED'}</td></tr>"
        for e in t.evidence_items
    )
    summary_json = json.dumps(t.summary, indent=2, default=str)

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>UC-04 run trace</title>
<style>
body {{ font-family: -apple-system, Segoe UI, sans-serif; margin: 2rem; color: #1a1a1a; background:#fafafa; }}
h1 {{ font-size: 1.3rem; }}
h2 {{ font-size: 1.05rem; margin-top: 2rem; border-bottom: 1px solid #ddd; padding-bottom: .25rem; }}
table {{ border-collapse: collapse; width: 100%; margin-top: .5rem; }}
td, th {{ border: 1px solid #ddd; padding: .35rem .5rem; font-size: .85rem; text-align: left; vertical-align: top; }}
.ai {{ color: #7a3; font-weight: 600; }}
.det {{ color: #555; }}
.pass {{ color: #1a7a1a; font-weight: 600; }}
.block {{ color: #b00020; font-weight: 600; }}
pre {{ white-space: pre-wrap; background: #fff; border: 1px solid #eee; padding: .5rem; font-size: .78rem; max-height: 300px; overflow: auto; }}
.callbox {{ background: #fcfcfc; padding: .5rem 1rem; border-left: 3px solid #7a3; margin: .25rem 0 1rem; }}
code {{ background:#eee; padding: 1px 4px; border-radius: 3px; }}
</style></head>
<body>
<h1>UC-04 &middot; From Validated Rules to Tested Code &mdash; run trace</h1>
<h2>Run header</h2>
<table>
<tr><th>Cases</th><td>{_esc(', '.join(t.header['case_ids']))}</td></tr>
<tr><th>Model</th><td>{_esc(t.header['model'])}</td></tr>
<tr><th>Temperature</th><td>{_esc(t.header['temperature'])}</td></tr>
<tr><th>Seed</th><td>{_esc(t.header['seed'])}</td></tr>
<tr><th>Config hash</th><td><code>{_esc(t.header['config_hash'])}</code></td></tr>
<tr><th>Git hash of ai/</th><td><code>{_esc(t.header['git_hash'])}</code></td></tr>
<tr><th>Started</th><td>{_esc(t.header['started_at'])}</td></tr>
</table>

<h2>Step timeline</h2>
<table><tr><th>Time</th><th>Step</th><th>Kind</th><th>ms</th><th>Detail</th></tr>{rows_steps}</table>

<h2>AI call detail</h2>
{rows_ai or '<p><i>No AI calls yet.</i></p>'}

<h2>Evidence panel (citations)</h2>
<table><tr><th>Source</th><th>Ref</th><th>Resolution</th></tr>{rows_evidence}</table>

<h2>Guardrail verdicts</h2>
<table><tr><th>Guardrail</th><th>Verdict</th><th>Reason</th></tr>{rows_guard}</table>

<h2>Abstentions</h2>
<table><tr><th>Layer</th><th>Item</th><th>Reason</th></tr>{rows_abst or ''}</table>
{'<p><i>No abstentions.</i></p>' if not t.abstentions else ''}

<h2>Run summary</h2>
<pre>{_esc(summary_json)}</pre>

</body></html>"""

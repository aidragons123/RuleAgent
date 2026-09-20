"""
streamlit_app.py - demo UI for UC-04, showing the pipeline live.

Not part of the original use-case deliverables (those are CLI: `make
demo`, `make test`, HTML traces). This is an additional, friendlier
front end over the same core.pipeline.Pipeline so the run and its
rule-by-rule validation report can be driven and read without a
terminal.

Run with: streamlit run streamlit_app.py   (or `make ui`)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai.implementation import BUG_VARIANTS  # noqa: E402
from core.pipeline import Pipeline, load_heldback_vectors, load_seed_vectors  # noqa: E402

st.set_page_config(
    page_title="UC-04 · From Validated Rules to Tested Code",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ----------------------------------------------------------------- style
# Fixed status palette (never themed / never reused for series color) —
# good/warning/serious/critical, each shipped with an icon + label so the
# status is never color-alone.
STATUS_META = {
    "VALIDATED":            {"bg": "#e6f7e6", "border": "#0ca30c", "text": "#0a6b0a", "icon": "✅", "label": "Validated — flawless"},
    "INVALIDATED_DEFECT":   {"bg": "#fbeaea", "border": "#d03b3b", "text": "#a52323", "icon": "❌", "label": "Invalidated — implementation defect"},
    "INVALIDATED_ROUNDING": {"bg": "#fdf0ea", "border": "#ec835a", "text": "#a3502f", "icon": "⚠️", "label": "Invalidated — rounding / representation"},
    "INVALIDATED_AMBIGUOUS":{"bg": "#fff6e0", "border": "#fab219", "text": "#8a6100", "icon": "❔", "label": "Invalidated — ambiguous rule text"},
    "UNCOVERABLE":          {"bg": "#f0f0ee", "border": "#898781", "text": "#5a5952", "icon": "◻️", "label": "Uncoverable"},
    "UNTESTED":             {"bg": "#f0f0ee", "border": "#898781", "text": "#5a5952", "icon": "◻️", "label": "Untested"},
}
STATUS_ORDER = ["VALIDATED", "INVALIDATED_DEFECT", "INVALIDATED_ROUNDING",
                "INVALIDATED_AMBIGUOUS", "UNCOVERABLE", "UNTESTED"]
STATUS_LABELS = {k: f"{v['icon']} {v['label'].upper()}" for k, v in STATUS_META.items()}
ACCENT_BLUE = "#2a78d6"  # informational, not a status — used for neutral counts (e.g. divergences)

st.markdown(
    """
    <style>
    .block-container { padding-top: 1.6rem; max-width: 1200px; }
    #MainMenu, footer { visibility: hidden; }

    .uc04-hero {
        background: linear-gradient(120deg, #16324f 0%, #1c4a7a 55%, #2a6fa8 100%);
        border-radius: 16px;
        padding: 1.8rem 2.2rem;
        color: #f4f8fc;
        margin-bottom: 1.4rem;
        box-shadow: 0 6px 20px rgba(20,40,70,0.18);
    }
    .uc04-hero h1 { margin: 0 0 .35rem 0; font-size: 1.7rem; font-weight: 700; color: #ffffff; }
    .uc04-hero p { margin: 0; opacity: .88; font-size: .95rem; line-height: 1.45; }

    .uc04-metric {
        border-radius: 12px;
        padding: 1rem 1.1rem;
        background: #ffffff10;
        border: 1px solid rgba(0,0,0,0.06);
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    }

    div[data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #eaecef;
        border-radius: 12px;
        padding: .9rem 1rem .6rem 1rem;
        box-shadow: 0 1px 4px rgba(0,0,0,0.04);
    }
    div[data-testid="stMetricLabel"] { font-weight: 600; opacity: .75; }

    .rule-card {
        border-radius: 14px;
        border: 1px solid #eaecef;
        border-left-width: 7px;
        padding: 1rem 1.2rem;
        margin-bottom: .7rem;
        background: #ffffff;
        box-shadow: 0 2px 10px rgba(20,36,58,0.05);
        transition: box-shadow .15s ease;
    }
    .rule-card:hover { box-shadow: 0 4px 16px rgba(20,36,58,0.10); }
    .rule-card .rule-id { font-weight: 800; font-size: 1.08rem; letter-spacing: .02em; color: #14243a; }
    .rule-card .rule-statement { color: #3a4453; margin: .2rem 0 .55rem 0; line-height: 1.45; }
    .status-pill {
        display: inline-block; padding: .32rem .8rem; border-radius: 999px;
        font-weight: 700; font-size: .78rem; letter-spacing: .02em; white-space: nowrap;
    }
    .meta-row { font-size: .82rem; color: #6b7280; margin-top: .4rem; display:flex; gap:1.1rem; flex-wrap:wrap; }
    .meta-row b { color: #14243a; }

    /* ---------------------------------------------------------- KPI tiles */
    .kpi-tile {
        border-radius: 16px;
        background: #ffffff;
        border: 1px solid #eaecef;
        border-top: 5px solid var(--accent, #2a78d6);
        padding: 1.1rem 1.3rem 1rem;
        box-shadow: 0 2px 10px rgba(20,36,58,0.05);
        height: 100%;
    }
    .kpi-tile .kpi-icon { font-size: 1.3rem; line-height: 1; }
    .kpi-tile .kpi-value { font-size: 2.3rem; font-weight: 800; color: #14243a; line-height: 1.15; margin-top: .25rem; }
    .kpi-tile .kpi-label { font-size: .86rem; font-weight: 600; color: #5a6472; margin-top: .1rem; }
    .kpi-tile .kpi-sub { font-size: .78rem; color: #8a94a1; margin-top: .2rem; }

    /* --------------------------------------------- segmented status bar */
    .status-bar-wrap { margin: .4rem 0 1.1rem; }
    .status-bar {
        display: flex; width: 100%; height: 34px; border-radius: 10px;
        overflow: hidden; background: #f0f0ee; border: 1px solid #eaecef;
    }
    .status-bar-seg {
        height: 100%; min-width: 3px;
        border-right: 2px solid #ffffff;
    }
    .status-bar-seg:last-child { border-right: none; }
    .status-legend {
        display: flex; flex-wrap: wrap; gap: .5rem .9rem; margin-top: .7rem;
    }
    .status-legend-item {
        display: flex; align-items: center; gap: .4rem;
        font-size: .84rem; color: #3a4453; font-weight: 600;
    }
    .status-legend-swatch {
        width: 11px; height: 11px; border-radius: 3px; display: inline-block;
    }
    .status-legend-count { color: #8a94a1; font-weight: 500; }

    /* ------------------------------------------- divergence comparison */
    .div-card {
        border-radius: 14px; border: 1px solid #eaecef; background: #ffffff;
        padding: .9rem 1.1rem; margin-bottom: .6rem; box-shadow: 0 1px 6px rgba(20,36,58,0.04);
    }
    .div-field-badge {
        display:inline-block; background:#eef2f8; color:#14243a; font-weight:700;
        font-size:.78rem; padding:.2rem .6rem; border-radius:6px; font-family: monospace;
    }
    .div-compare { display:flex; gap:.8rem; margin-top:.6rem; }
    .div-box { flex:1; border-radius:10px; padding:.6rem .8rem; }
    .div-box.expected { background:#e6f7e6; border:1px solid #0ca30c33; }
    .div-box.actual { background:#fbeaea; border:1px solid #d03b3b33; }
    .div-box .div-box-label { font-size:.72rem; font-weight:700; letter-spacing:.03em; text-transform:uppercase; opacity:.7; }
    .div-box .div-box-value { font-size:1.15rem; font-weight:800; font-family: monospace; margin-top:.1rem; }

    /* --- Pin a light theme regardless of the browser/OS dark-mode setting.
       Streamlit's dark theme drives almost everything through these CSS
       variables, so overriding them at :root (not just individual
       elements) is what actually stops black backgrounds / invisible
       white-on-white text from reappearing. Belt-and-braces explicit
       overrides on the concrete containers follow below. */
    :root, .stApp {
        --background-color: #ffffff !important;
        --secondary-background-color: #f7f9fb !important;
        --text-color: #14243a !important;
        --primary-color: #d6402e !important;
        color-scheme: light !important;
    }

    html, body,
    .stApp,
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"],
    [data-testid="stHeader"],
    [data-testid="stBottomBlockContainer"],
    .main {
        background: #ffffff !important;
        color: #14243a !important;
    }

    [data-testid="stAppViewContainer"] *,
    [data-testid="stMain"] * {
        color: #14243a !important;
    }

    section[data-testid="stSidebar"],
    section[data-testid="stSidebar"] > div {
        background: #f7f9fb !important;
        color: #14243a !important;
    }
    section[data-testid="stSidebar"] * {
        color: #14243a !important;
    }
    /* Buttons keep white text on their own colored fill. */
    section[data-testid="stSidebar"] .stButton button,
    [data-testid="stMain"] .stButton button {
        color: #ffffff !important;
    }
    /* Don't force color on icon glyphs / svg fills, they carry their own. */
    section[data-testid="stSidebar"] svg,
    [data-testid="stMain"] svg {
        color: inherit;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_pipeline() -> Pipeline:
    return Pipeline()


def run_scope(scope: str):
    pipeline = get_pipeline()
    heldback = load_heldback_vectors()
    seed = load_seed_vectors()

    if scope == "Full run (all 24 rules, all vectors)":
        return pipeline.run(include_synthesised=True, extra_vectors=seed + heldback,
                             run_id="ui-full")
    if scope == "Happy flow (R-004..R-008, R-014, R-016, R-017)":
        return pipeline.run(include_synthesised=True, extra_vectors=[], run_id="ui-happy",
                             synthesis_rule_ids=["R-004", "R-005", "R-006", "R-007",
                                                  "R-008", "R-014", "R-016", "R-017"])
    if scope == "Rounding (R-009)":
        return pipeline.run(include_synthesised=True, extra_vectors=[], run_id="ui-rounding",
                             synthesis_rule_ids=["R-009"])
    if scope == "Untraceable cap behaviour":
        cap_vectors = [v for v in heldback if "cap" in v.note.lower()]
        return pipeline.run(include_synthesised=False, extra_vectors=cap_vectors,
                             run_id="ui-untraceable")
    raise ValueError(scope)


# ------------------------------------------------------------------ hero
st.markdown(
    """
    <div class="uc04-hero">
        <h1>🧪 UC-04 · From Validated Rules to Tested Code</h1>
        <p>AI-assisted COBOL modernisation pipeline — synthesises tests straight from
        SME-approved business rules, generates a Python reimplementation, diffs it against
        a real, compiled GnuCOBOL oracle, and renders a rule-by-rule change-approval report:
        exactly which rules are flawless, and which are flawed — and on which side.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

VARIANT_OPTIONS = {
    "✅ Clean (code generated properly)": None,
    **{f"❌ Bug injected: {v['description']}": key for key, v in BUG_VARIANTS.items()},
}

with st.sidebar:
    st.markdown("### ⚙️ Run the pipeline")
    scope = st.selectbox("Scope", [
        "Full run (all 24 rules, all vectors)",
        "Happy flow (R-004..R-008, R-014, R-016, R-017)",
        "Rounding (R-009)",
        "Untraceable cap behaviour",
    ])
    st.divider()
    st.markdown("### 🧬 Code variant")
    st.caption(
        "The two practical scenarios: run the SAME rules against the SAME "
        "generated code — clean vs. with one real bug injected."
    )
    variant_label = st.radio("Generated implementation", list(VARIANT_OPTIONS.keys()),
                              label_visibility="collapsed")
    bug = VARIANT_OPTIONS[variant_label]
    run_clicked = st.button("▶  Run pipeline", type="primary", use_container_width=True)
    st.divider()
    st.caption(
        "LLM mode: set in `ai_platform/config.yaml` (`llm.mode: mock|real`). "
        "Mock mode (default) is fully offline and deterministic — no API key needed."
    )

if run_clicked:
    if bug:
        os.environ["UC04_INJECT_BUG"] = bug
    else:
        os.environ.pop("UC04_INJECT_BUG", None)
    with st.spinner(f"Running: {scope} ({'clean' if not bug else bug})..."):
        st.session_state["result"] = run_scope(scope)
        st.session_state["scope"] = scope
        st.session_state["bug"] = bug
    os.environ.pop("UC04_INJECT_BUG", None)

result = st.session_state.get("result")

if result is None:
    st.info("👈 Choose a scope and code variant in the sidebar, then click **Run pipeline**.")
    st.stop()

facts = result.facts
active_bug = st.session_state.get("bug")

if active_bug:
    v = BUG_VARIANTS[active_bug]
    st.error(
        f"🐞 **Bug injected: `{active_bug}`** — {v['description']} "
        f"Expect **{v['rule_id']}** to show INVALIDATED below (flaw side: code)."
    )
else:
    st.success("✅ **Clean generated code** — no bug injected. Any real divergence below "
               "is a genuine ambiguous-rule, rounding, or untraceable-behaviour finding, "
               "not an implementation defect.")

# --------------------------------------------------------------- metrics
def kpi_tile(icon: str, value, label: str, accent: str, sub: str = "") -> str:
    sub_html = f'<div class="kpi-sub">{sub}</div>' if sub else ""
    return f"""
    <div class="kpi-tile" style="--accent:{accent};">
        <div class="kpi-icon">{icon}</div>
        <div class="kpi-value">{value}</div>
        <div class="kpi-label">{label}</div>
        {sub_html}
    </div>
    """

total_rules = facts.rules_validated + facts.rules_invalidated + facts.rules_uncoverable
pct = f"{facts.rules_validated / total_rules:.0%}" if total_rules else "—"

k1, k2, k3, k4 = st.columns(4)
k1.markdown(kpi_tile("✅", facts.rules_validated, "Validated — flawless",
                      STATUS_META["VALIDATED"]["border"]), unsafe_allow_html=True)
k2.markdown(kpi_tile("❌", facts.rules_invalidated, "Invalidated — flaw found",
                      STATUS_META["INVALIDATED_DEFECT"]["border"]), unsafe_allow_html=True)
k3.markdown(kpi_tile("◻️", facts.rules_uncoverable, "Uncoverable / untested",
                      STATUS_META["UNCOVERABLE"]["border"]), unsafe_allow_html=True)
k4.markdown(kpi_tile("🔍", facts.total_divergences, "Divergences found", ACCENT_BLUE,
                      sub=f"over {facts.total_vectors} test vectors"), unsafe_allow_html=True)

st.write("")

if total_rules:
    st.progress(facts.rules_validated / total_rules,
                text=f"**{facts.rules_validated} of {total_rules} rules validated ({pct})**")

# ------------------------------------------------- segmented status bar
status_counts = pd.Series([row.status for row in facts.traceability]).value_counts()
counts_by_status = {s: int(status_counts.get(s, 0)) for s in STATUS_ORDER}
total_for_bar = sum(counts_by_status.values())

if total_for_bar:
    segments_html = "".join(
        f'<div class="status-bar-seg" title="{STATUS_META[s]["label"]}: {n}" '
        f'style="width:{n / total_for_bar * 100:.3f}%; background:{STATUS_META[s]["border"]};"></div>'
        for s, n in counts_by_status.items() if n > 0
    )
    legend_html = "".join(
        f'<span class="status-legend-item">'
        f'<span class="status-legend-swatch" style="background:{STATUS_META[s]["border"]};"></span>'
        f'{STATUS_META[s]["icon"]} {STATUS_META[s]["label"]} '
        f'<span class="status-legend-count">({n})</span></span>'
        for s, n in counts_by_status.items() if n > 0
    )
    st.markdown(
        f"""
        <div class="status-bar-wrap">
            <div class="status-bar">{segments_html}</div>
            <div class="status-legend">{legend_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.write("")

tabs = st.tabs(["📋 Rule validation report", "🕵️ Untraceable findings", "📄 Evidence pack sections",
                "🔬 Divergence gallery", "🔗 Links & downloads"])

with tabs[0]:
    st.subheader("Every rule, validated or invalidated")
    status_filter = st.multiselect(
        "Filter by status", options=sorted(STATUS_LABELS, key=lambda k: k),
        format_func=lambda k: STATUS_LABELS[k], default=[],
    )
    rows = facts.traceability
    if status_filter:
        rows = [r for r in rows if r.status in status_filter]

    for row in rows:
        meta = STATUS_META.get(row.status, {"bg": "#fff", "border": "#ccc", "text": "#333",
                                             "icon": "•", "label": row.status})
        st.markdown(
            f"""
            <div class="rule-card" style="border-left-color:{meta['border']};">
                <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:1rem;">
                    <div style="flex:1;">
                        <span class="rule-id">{row.rule_id}</span>
                        <div class="rule-statement">{row.statement}</div>
                    </div>
                    <span class="status-pill" style="background:{meta['bg']}; color:{meta['text']};">
                        {meta['icon']} {meta['label'].upper()}
                    </span>
                </div>
                <div class="meta-row">
                    Flaw side: <b>{row.flaw_side}</b> &nbsp;·&nbsp;
                    Citing tests: <b>{len(row.tests)}</b> &nbsp;·&nbsp;
                    Citing code: <b>{', '.join(row.code_citations) or '—'}</b>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if row.diagnoses:
            with st.expander(f"{len(row.diagnoses)} diagnosis(es) for {row.rule_id}"):
                for d in row.diagnoses:
                    st.markdown(f"- **{d.vector_id}** ({d.cause}): {d.explanation}")
                    if d.fix_suggested:
                        st.caption(f"  Suggested: {d.fix_suggested}")

with tabs[1]:
    st.subheader("Code paths no rule describes")
    if not facts.untraceable_findings:
        st.success("None found in this run's vector set.")
    for f in facts.untraceable_findings:
        st.warning(f"**{f.id}**: {f.description}")
        st.caption(f"Triggering vectors: {', '.join(f.triggering_vectors)}")

with tabs[2]:
    st.subheader("Change-approval evidence pack sections")
    for kind, text in result.sections.items():
        st.markdown(f"**{kind.replace('_', ' ').title()}**")
        st.write(text)

with tabs[3]:
    st.subheader("Divergence gallery")
    st.caption("Every field-level disagreement between the compiled COBOL oracle and the "
               "generated modern code, for every test vector run.")
    for d in result.divergences[:50]:
        st.markdown(
            f"""
            <div class="div-card">
                <span class="div-field-badge">{d.vector_id}</span>
                &nbsp; field <span class="div-field-badge">{d.field}</span>
                <div class="div-compare">
                    <div class="div-box expected">
                        <div class="div-box-label">🗄️ COBOL (expected)</div>
                        <div class="div-box-value">{d.expected!r}</div>
                    </div>
                    <div class="div-box actual">
                        <div class="div-box-label">☕ Modern code (actual)</div>
                        <div class="div-box-value">{d.actual!r}</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.expander("Full input / output for this vector"):
            st.json({"input": d.input, "cobol_output": d.cobol_output,
                     "modern_output": d.modern_output})
    if len(result.divergences) > 50:
        st.caption(f"... and {len(result.divergences) - 50} more. See the HTML trace for all of them.")

with tabs[4]:
    st.write(f"HTML trace: `{result.trace_path}`")
    st.write(f"Evidence pack: `{result.evidence_path}`")
    try:
        dl1, dl2 = st.columns(2)
        dl1.download_button("⬇ Download evidence pack (HTML)",
                             data=Path(result.evidence_path).read_bytes(),
                             file_name="evidence_pack.html", mime="text/html",
                             use_container_width=True)
        dl2.download_button("⬇ Download run trace (HTML)",
                             data=Path(result.trace_path).read_bytes(),
                             file_name=Path(result.trace_path).name, mime="text/html",
                             use_container_width=True)
    except Exception as exc:
        st.caption(f"(download unavailable: {exc})")

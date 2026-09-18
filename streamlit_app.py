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

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai.implementation import BUG_VARIANTS  # noqa: E402
from core.pipeline import Pipeline, load_heldback_vectors, load_seed_vectors  # noqa: E402

st.set_page_config(page_title="UC-04 · From Validated Rules to Tested Code", layout="wide")

STATUS_COLORS = {
    "VALIDATED": "#e6f6e6",
    "INVALIDATED_DEFECT": "#fdeaea",
    "INVALIDATED_ROUNDING": "#fff6e0",
    "INVALIDATED_AMBIGUOUS": "#fff6e0",
    "UNCOVERABLE": "#f0f0f0",
    "UNTESTED": "#f0f0f0",
}
STATUS_LABELS = {
    "VALIDATED": "✅ VALIDATED — flawless",
    "INVALIDATED_DEFECT": "❌ INVALIDATED — implementation defect",
    "INVALIDATED_ROUNDING": "⚠️ INVALIDATED — rounding/representation",
    "INVALIDATED_AMBIGUOUS": "⚠️ INVALIDATED — ambiguous rule text",
    "UNCOVERABLE": "◻️ UNCOVERABLE",
    "UNTESTED": "◻️ UNTESTED",
}


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


st.title("UC-04 · From Validated Rules to Tested Code")
st.caption(
    "AI-assisted COBOL modernisation pipeline — test synthesis, implementation, "
    "divergence diagnosis and evidence generation against a golden GnuCOBOL runtime."
)

VARIANT_OPTIONS = {
    "✅ Clean (code generated properly)": None,
    **{f"❌ Bug injected: {v['description']}": key for key, v in BUG_VARIANTS.items()},
}

with st.sidebar:
    st.header("Run the pipeline")
    scope = st.selectbox("Scope", [
        "Full run (all 24 rules, all vectors)",
        "Happy flow (R-004..R-008, R-014, R-016, R-017)",
        "Rounding (R-009)",
        "Untraceable cap behaviour",
    ])
    st.divider()
    st.subheader("Code variant")
    st.caption(
        "The two practical scenarios: run the SAME rules against the SAME "
        "generated code, clean vs. with one real bug injected."
    )
    variant_label = st.radio("Generated implementation", list(VARIANT_OPTIONS.keys()))
    bug = VARIANT_OPTIONS[variant_label]
    run_clicked = st.button("▶ Run", type="primary", use_container_width=True)
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
    st.info("Choose a scope in the sidebar and click **Run** to execute the pipeline.")
    st.stop()

facts = result.facts
active_bug = st.session_state.get("bug")

if active_bug:
    v = BUG_VARIANTS[active_bug]
    st.error(
        f"**Bug injected: `{active_bug}`** — {v['description']} "
        f"Expect **{v['rule_id']}** to show INVALIDATED below (flaw side: code)."
    )
else:
    st.success("**Clean generated code** — no bug injected. Rules with a real "
               "divergence below are genuine ambiguous-rule, rounding, or "
               "untraceable-behaviour findings, not implementation defects.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Rules validated (flawless)", facts.rules_validated)
c2.metric("Rules invalidated (flaw found)", facts.rules_invalidated)
c3.metric("Rules uncoverable / untested", facts.rules_uncoverable)
c4.metric("Divergences", facts.total_divergences, f"over {facts.total_vectors} vectors")

tabs = st.tabs(["Rule validation report", "Untraceable findings", "Evidence pack sections",
                "Divergence gallery", "Links"])

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
        color = STATUS_COLORS.get(row.status, "#fff")
        with st.container(border=True):
            cols = st.columns([1, 4, 3])
            cols[0].markdown(f"**{row.rule_id}**")
            cols[1].write(row.statement)
            cols[2].markdown(
                f"<div style='background:{color};padding:.3rem .6rem;border-radius:6px;"
                f"font-weight:600;'>{STATUS_LABELS.get(row.status, row.status)}</div>",
                unsafe_allow_html=True,
            )
            meta_cols = st.columns(3)
            meta_cols[0].caption(f"Flaw side: **{row.flaw_side}**")
            meta_cols[1].caption(f"Citing tests: {len(row.tests)}")
            meta_cols[2].caption(f"Citing code: {', '.join(row.code_citations) or '—'}")
            if row.diagnoses:
                with st.expander(f"{len(row.diagnoses)} diagnosis(es)"):
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
    for d in result.divergences[:50]:
        with st.expander(f"{d.vector_id} · field `{d.field}`: expected {d.expected!r}, got {d.actual!r}"):
            st.json({"input": d.input, "cobol_output": d.cobol_output,
                     "python_output": d.python_output})
    if len(result.divergences) > 50:
        st.caption(f"... and {len(result.divergences) - 50} more. See the HTML trace for all of them.")

with tabs[4]:
    st.write(f"HTML trace: `{result.trace_path}`")
    st.write(f"Evidence pack: `{result.evidence_path}`")
    try:
        st.download_button("Download evidence pack (HTML)",
                            data=Path(result.evidence_path).read_bytes(),
                            file_name="evidence_pack.html", mime="text/html")
        st.download_button("Download run trace (HTML)",
                            data=Path(result.trace_path).read_bytes(),
                            file_name=Path(result.trace_path).name, mime="text/html")
    except Exception as exc:
        st.caption(f"(download unavailable: {exc})")

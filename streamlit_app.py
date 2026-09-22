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

import datetime as _dt
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai.bug_injector import BugInjectorAI  # noqa: E402
from ai.implementation import BUG_VARIANTS  # noqa: E402
from ai_platform.config import get_config  # noqa: E402
from core.pipeline import Pipeline, load_heldback_vectors, load_seed_vectors  # noqa: E402

st.set_page_config(
    page_title="CodeVerus — From Legacy COBOL to Verified Modern Code",
    page_icon="⚖️",
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
ACCENT_NEUTRAL = "#7c56d6"  # informational, not a status — used for neutral counts (e.g. divergences)

st.markdown(
    """
    <style>
    .block-container { padding-top: 1.6rem; max-width: 1200px; }
    #MainMenu, footer { visibility: hidden; }

    .uc04-hero {
        background: #ffffff;
        border: 1px solid #e6e8eb;
        border-left: 5px solid #14243a;
        border-radius: 14px;
        padding: 1.7rem 2.1rem;
        color: #14243a;
        margin-bottom: 1.4rem;
        box-shadow: 0 2px 12px rgba(20,36,58,0.06);
    }
    .uc04-hero h1 { margin: 0 0 .35rem 0; font-size: 1.6rem; font-weight: 800; color: #14243a; }
    .uc04-hero p { margin: 0; color: #4a5568; font-size: .95rem; line-height: 1.5; }

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

    /* Source-code viewer (st.code): dark background, white text — this
       overrides the global dark-text rule above, which otherwise made
       code unreadable (dark text on the code block's own dark background). */
    [data-testid="stCode"] {
        background: #1e1e2e !important;
        border-radius: 10px !important;
    }
    [data-testid="stCode"] pre,
    [data-testid="stCode"] code,
    [data-testid="stCode"] span,
    [data-testid="stCode"] * {
        color: #ffffff !important;
        background: transparent !important;
    }
    [data-testid="stCode"] .linenumber {
        color: #9aa0ab !important;
    }

    /* ---------------------------------------------------- colored sidebar */
    section[data-testid="stSidebar"],
    section[data-testid="stSidebar"] > div {
        background: linear-gradient(180deg, #1c2128 0%, #262c35 55%, #2f3542 100%) !important;
        color: #eef0f3 !important;
    }
    section[data-testid="stSidebar"] * {
        color: #eef0f3 !important;
    }
    section[data-testid="stSidebar"] h3 {
        font-weight: 800 !important; letter-spacing: .01em;
    }
    section[data-testid="stSidebar"] hr {
        border-color: #ffffff2a !important;
    }
    /* Card-grouped sections (st.container(border=True)) inside the sidebar */
    section[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] {
        background: #ffffff0f !important;
        border: 1px solid #ffffff26 !important;
        border-left: 4px solid #f0b23e !important;
        border-radius: 12px !important;
        padding: .3rem .4rem !important;
        margin-bottom: .9rem !important;
    }
    /* Slight color variety between the sidebar sections — no blue */
    section[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]:nth-of-type(2) {
        border-left-color: #e0729c !important;
    }
    section[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]:nth-of-type(3) {
        border-left-color: #8b6fd1 !important;
    }
    /* The scope dropdown reads better as a light control against the dark panel */
    section[data-testid="stSidebar"] [data-baseweb="select"] > div {
        background: #ffffff !important;
        border-radius: 8px !important;
        border: 1px solid #ffffff40 !important;
    }
    section[data-testid="stSidebar"] [data-baseweb="select"] * {
        color: #14243a !important;
    }
    section[data-testid="stSidebar"] .stCaption, section[data-testid="stSidebar"] small {
        color: #b9cbe0 !important;
    }
    section[data-testid="stSidebar"] code {
        background: #ffffff1a !important; color: #d7e6f5 !important;
    }
    /* Buttons keep white text on their own colored fill. */
    section[data-testid="stSidebar"] .stButton button,
    [data-testid="stMain"] .stButton button {
        color: #ffffff !important;
        background: linear-gradient(120deg, #e0503a 0%, #d6402e 100%) !important;
        border: none !important;
        font-weight: 700 !important;
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


RUNS_DIR = Path(__file__).resolve().parent / "runs"


def autosave_run(result, label: str) -> Path:
    """Copy this run's generated Java, evidence pack, and trace into a
    timestamped folder under runs/, so nothing is lost between app
    restarts or overwritten by the next click - every run any presenter
    has ever made stays on disk, not just the most recent one."""
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)[:60]
    out_dir = RUNS_DIR / f"{ts}_{safe_label}"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        (out_dir / Path(result.source.path).name).write_text(result.source.content)
    except Exception:
        pass
    for attr, dest_name in (("evidence_path", "evidence_pack.html"), ("trace_path", None)):
        src = getattr(result, attr, None)
        if not src:
            continue
        src = Path(src)
        if src.exists():
            try:
                (out_dir / (dest_name or src.name)).write_bytes(src.read_bytes())
            except Exception:
                pass
    return out_dir


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
        <h1>CodeVerus — From Legacy COBOL to Verified Modern Code</h1>
        <p>Takes a legacy COBOL program, generates a real, compiled Java replacement for it,
        and validates that replacement against SME-approved business rules — producing a
        rule-by-rule report of exactly which rules are flawless, and which are flawed, and on
        which side.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

SCOPE_OPTIONS = {
    "Full run": {
        "value": "Full run (all 24 rules, all vectors)",
        "help": "Every one of the 24 rules, checked against every test vector.",
    },
    "Happy flow": {
        "value": "Happy flow (R-004..R-008, R-014, R-016, R-017)",
        "help": "Just the tiered-interest rate rules (R-004–R-008, R-014, R-016, R-017).",
    },
    "Rounding only": {
        "value": "Rounding (R-009)",
        "help": "Just R-009, the interest-rounding rule.",
    },
    "Untraceable cap behaviour": {
        "value": "Untraceable cap behaviour",
        "help": "A code path no rule describes — shows the agent's honesty guardrail.",
    },
}

VARIANT_OPTIONS = {
    "Clean": {"value": None, "help": "Code generated correctly — no bug injected."},
    **{
        f"Bug: {v['rule_id']}": {"value": key, "help": v["description"]}
        for key, v in BUG_VARIANTS.items()
    },
}

with st.sidebar:
    st.markdown("## CodeVerus")
    st.caption("AI COBOL modernization & rule validation")
    st.write("")

    with st.container(border=True):
        st.markdown("#### 1. Choose what to test")
        scope_key = st.selectbox(
            "Scope", list(SCOPE_OPTIONS.keys()), label_visibility="collapsed",
        )
        scope = SCOPE_OPTIONS[scope_key]["value"]
        st.caption(SCOPE_OPTIONS[scope_key]["help"])

    with st.container(border=True):
        st.markdown("#### 2. Choose the code to check")
        st.caption(
            "Run the same rules against the same generated code — clean, "
            "or with one real bug injected on purpose."
        )
        variant_key = st.radio(
            "Generated implementation", list(VARIANT_OPTIONS.keys()),
            label_visibility="collapsed",
        )
        bug = VARIANT_OPTIONS[variant_key]["value"]
        st.caption(f"→ {VARIANT_OPTIONS[variant_key]['help']}")

    run_clicked = st.button("▶  Run pipeline", type="primary", use_container_width=True)

    prior_result = st.session_state.get("result")
    with st.container(border=True):
        st.markdown("#### 3. AI bug injection")
        if prior_result is None:
            st.caption(
                "Run the pipeline once (clean) above first — then come back here to "
                "have the LLM introduce its own bug into that generated code and "
                "re-validate, without regenerating anything."
            )
            target_rule_id = None
            inject_clicked = False
        else:
            rule_ids = [r.id for r in prior_result.rules]
            target_rule_id = st.selectbox(
                "Rule to break", rule_ids, label_visibility="collapsed",
            )
            llm_mode = os.environ.get("UC04_LLM_MODE", get_config()["llm"]["mode"])
            if llm_mode == "real":
                st.caption(
                    f"→ Asks Claude to introduce one realistic defect into the last "
                    f"generated code, targeting **{target_rule_id}**, then re-runs the "
                    f"same test vectors against it — no regeneration."
                )
            else:
                st.caption(
                    "→ Currently in **mock mode**: uses the same 3 built-in canned bugs "
                    "(by rule id) as option 2 above, applied to the last generated code. "
                    "Set `llm.mode: real` in `ai_platform/config.yaml` for Claude to "
                    "author a genuinely new bug."
                )
            inject_clicked = st.button(
                "🐛  Inject AI bug & re-validate", use_container_width=True,
            )

    with st.container(border=True):
        st.markdown("#### 4. Modify a rule & re-validate")
        if prior_result is None:
            st.caption(
                "Run the pipeline once (clean) above first — then come back here to "
                "change one rule's wording and see the generated code — and the "
                "report — react to it. This never edits validated_rules.yaml on "
                "disk; the change only applies to this one run."
            )
            rule_change_id = None
            rule_change_text = ""
            rule_change_clicked = False
        else:
            rule_change_id = st.selectbox(
                "Rule to modify", [r.id for r in prior_result.rules],
                label_visibility="collapsed", key="rule_change_select",
            )
            current_statement = next(
                (r.statement for r in prior_result.rules if r.id == rule_change_id), "",
            )
            rule_change_text = st.text_area(
                "New wording", value=current_statement, height=100,
                label_visibility="collapsed", key=f"rule_change_text_{rule_change_id}",
            )
            llm_mode_rc = os.environ.get("UC04_LLM_MODE", get_config()["llm"]["mode"])
            if llm_mode_rc == "real":
                st.caption(
                    "→ Regenerates the implementation from this new wording, then "
                    "compares it against the (unchanged) legacy COBOL — a realistic "
                    "'the requirement changed, the old system didn't' scenario."
                )
            else:
                st.caption(
                    "⚠️ Currently in **mock mode**: the generated code is a fixed "
                    "template that ignores rule wording, so this will show no "
                    "effect. Set `llm.mode: real` in `ai_platform/config.yaml` to "
                    "see Claude actually implement your new wording."
                )
            rule_change_clicked = st.button(
                "✏️  Modify rule & re-validate", use_container_width=True,
            )


if run_clicked:
    # Keep the run this button-click is about to replace, so a "compare
    # with previous run" view is possible without re-running anything.
    if st.session_state.get("result") is not None:
        st.session_state["prev_result"] = st.session_state["result"]
        st.session_state["prev_label"] = st.session_state.get("run_label", "previous run")

    if bug:
        os.environ["UC04_INJECT_BUG"] = bug
    else:
        os.environ.pop("UC04_INJECT_BUG", None)
    with st.spinner(f"Running: {scope} ({'clean' if not bug else bug})..."):
        new_result = run_scope(scope)
        st.session_state["result"] = new_result
        st.session_state["scope"] = scope
        st.session_state["bug"] = bug
        st.session_state["ai_bug"] = None
        st.session_state["rule_change"] = None
        run_label = f"{scope_key} · {variant_key}"
        st.session_state["run_label"] = run_label
    os.environ.pop("UC04_INJECT_BUG", None)

    save_dir = autosave_run(new_result, run_label)
    st.session_state["last_save_dir"] = str(save_dir)
    st.session_state.setdefault("run_history", []).append({
        "Time": _dt.datetime.now().strftime("%H:%M:%S"),
        "Scope": scope_key,
        "Code variant": variant_key,
        "Validated": new_result.facts.rules_validated,
        "Invalidated": new_result.facts.rules_invalidated,
        "Uncoverable/Untested": new_result.facts.rules_uncoverable,
        "Divergences": new_result.facts.total_divergences,
        "Saved to": str(save_dir),
    })
    # Rerun once so the sidebar's "3. AI bug injection" section (which reads
    # the just-saved result) reflects it immediately, instead of one click later.
    st.rerun()

if inject_clicked and target_rule_id is not None:
    prior = st.session_state.get("result")
    if prior is None:
        st.warning("Run the pipeline once (clean) before injecting an AI-authored bug.")
    else:
        st.session_state["prev_result"] = prior
        st.session_state["prev_label"] = st.session_state.get("run_label", "previous run")
        with st.spinner(f"Asking the LLM to break {target_rule_id}..."):
            injection = BugInjectorAI().inject(prior.source, prior.rules, target_rule_id)
        if injection.abstained:
            st.error(f"Bug injection abstained: {injection.abstain_reason}")
        else:
            mutated = injection.value
            new_result = get_pipeline().validate_source(
                mutated, prior.vectors, run_id="ui-ai-bug",
            )
            st.session_state["result"] = new_result
            st.session_state["bug"] = None
            st.session_state["ai_bug"] = {
                "rule_id": target_rule_id, "description": mutated.bug_description,
            }
            st.session_state["rule_change"] = None
            run_label = f"{st.session_state.get('run_label', 'previous run')} · AI bug: {target_rule_id}"
            st.session_state["run_label"] = run_label

            save_dir = autosave_run(new_result, run_label)
            st.session_state["last_save_dir"] = str(save_dir)
            st.session_state.setdefault("run_history", []).append({
                "Time": _dt.datetime.now().strftime("%H:%M:%S"),
                "Scope": "(same vectors as previous run)",
                "Code variant": f"AI-injected bug: {target_rule_id}",
                "Validated": new_result.facts.rules_validated,
                "Invalidated": new_result.facts.rules_invalidated,
                "Uncoverable/Untested": new_result.facts.rules_uncoverable,
                "Divergences": new_result.facts.total_divergences,
                "Saved to": str(save_dir),
            })

if rule_change_clicked and rule_change_id is not None:
    prior = st.session_state.get("result")
    if prior is None:
        st.warning("Run the pipeline once (clean) before modifying a rule.")
    elif not rule_change_text.strip():
        st.warning("Enter the new rule wording before re-validating.")
    else:
        st.session_state["prev_result"] = prior
        st.session_state["prev_label"] = st.session_state.get("run_label", "previous run")
        old_statement = next(
            (r.statement for r in prior.rules if r.id == rule_change_id), "",
        )
        llm_mode_now = os.environ.get("UC04_LLM_MODE", get_config()["llm"]["mode"])
        with st.spinner(f"Regenerating the implementation from the new wording of {rule_change_id}..."):
            new_result = get_pipeline().modify_rule_and_revalidate(
                rule_change_id, rule_change_text.strip(), prior.vectors, run_id="ui-rule-change",
            )
        st.session_state["result"] = new_result
        st.session_state["bug"] = None
        st.session_state["ai_bug"] = None
        st.session_state["rule_change"] = {
            "rule_id": rule_change_id, "old_statement": old_statement,
            "new_statement": rule_change_text.strip(), "mock_mode": llm_mode_now != "real",
        }
        run_label = f"{st.session_state.get('run_label', 'previous run')} · rule changed: {rule_change_id}"
        st.session_state["run_label"] = run_label

        save_dir = autosave_run(new_result, run_label)
        st.session_state["last_save_dir"] = str(save_dir)
        st.session_state.setdefault("run_history", []).append({
            "Time": _dt.datetime.now().strftime("%H:%M:%S"),
            "Scope": "(same vectors as previous run)",
            "Code variant": f"Rule changed: {rule_change_id}",
            "Validated": new_result.facts.rules_validated,
            "Invalidated": new_result.facts.rules_invalidated,
            "Uncoverable/Untested": new_result.facts.rules_uncoverable,
            "Divergences": new_result.facts.total_divergences,
            "Saved to": str(save_dir),
        })

result = st.session_state.get("result")

if result is None:
    st.info("👈 Choose a scope and code variant in the sidebar, then click **Run pipeline**.")
    st.stop()

facts = result.facts
active_bug = st.session_state.get("bug")
active_ai_bug = st.session_state.get("ai_bug")
active_rule_change = st.session_state.get("rule_change")

if active_rule_change:
    if active_rule_change.get("mock_mode"):
        st.warning(
            f"⚠️ **Rule `{active_rule_change['rule_id']}` reworded — but this ran in "
            f"mock mode**, so the generated code is unchanged (mock ignores rule "
            f"wording). Switch to real mode to see Claude actually implement: "
            f"\"{active_rule_change['new_statement']}\""
        )
    else:
        st.error(
            f"📝 **Rule `{active_rule_change['rule_id']}` reworded** — was: "
            f"\"{active_rule_change['old_statement']}\" → now: "
            f"\"{active_rule_change['new_statement']}\". The implementation was "
            f"regenerated from this new wording; the frozen legacy COBOL didn't "
            f"change, so expect a genuine divergence — a requirement-drift finding, "
            f"not a coding mistake."
        )
elif active_ai_bug:
    st.error(
        f"🐞 **AI-injected bug — rule `{active_ai_bug['rule_id']}`** — "
        f"{active_ai_bug['description']} Expect **{active_ai_bug['rule_id']}** to show "
        f"INVALIDATED below (flaw side: code)."
    )
elif active_bug:
    v = BUG_VARIANTS[active_bug]
    st.error(
        f"🐞 **Bug injected: `{active_bug}`** — {v['description']} "
        f"Expect **{v['rule_id']}** to show INVALIDATED below (flaw side: code)."
    )
else:
    st.success("✅ **Clean generated code** — no bug injected. Any real divergence below "
               "is a genuine ambiguous-rule, rounding, or untraceable-behaviour finding, "
               "not an implementation defect.")

last_save_dir = st.session_state.get("last_save_dir")
if last_save_dir:
    st.caption(f"💾 This run was auto-saved to `{last_save_dir}` (generated code, evidence pack, trace).")

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
k4.markdown(kpi_tile("🔍", facts.total_divergences, "Divergences found", ACCENT_NEUTRAL,
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

tabs = st.tabs(["📋 Rule validation report", "🧾 Test vectors", "🔀 Compare runs",
                "🕘 Run history", "🕵️ Untraceable findings", "📄 Evidence pack sections",
                "🔬 Divergence gallery", "🧑‍💻 Source code", "🔗 Links & downloads"])

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
    st.subheader("Every test vector used in this run")
    st.caption(
        "The actual inputs fed to both the COBOL oracle and the generated code — "
        "before any pass/fail judgment is applied. Proof the test data is real "
        "and varied, not cherry-picked."
    )
    vec_rows = []
    diverged_ids = {d.vector_id for d in result.divergences}
    for v in result.vectors:
        row = {"Vector ID": v.id, "Origin": v.origin.replace("_", " "),
               "Rule(s)": ", ".join(v.rule_ids) or "—",
               "Diverged?": "⚠️ yes" if v.id in diverged_ids else "no"}
        row.update(v.input)
        vec_rows.append(row)
    if vec_rows:
        st.dataframe(pd.DataFrame(vec_rows), use_container_width=True, hide_index=True)
        st.caption(f"{len(vec_rows)} vectors total.")
    else:
        st.info("No test vectors recorded for this run.")

with tabs[2]:
    st.subheader("Compare this run with the previous one")
    prev = st.session_state.get("prev_result")
    if prev is None:
        st.info(
            "No previous run yet this session. Run the pipeline once (e.g. **Clean**), "
            "then change the code variant and run again — this tab will show both "
            "runs side by side."
        )
    else:
        prev_label = st.session_state.get("prev_label", "Previous run")
        curr_label = st.session_state.get("run_label", "Current run")
        cprev, ccurr = st.columns(2)
        for col, label, r in [(cprev, prev_label, prev), (ccurr, curr_label, result)]:
            with col:
                st.markdown(f"**{label}**")
                f = r.facts
                st.markdown(
                    f"✅ Validated: **{f.rules_validated}** &nbsp;·&nbsp; "
                    f"❌ Invalidated: **{f.rules_invalidated}** &nbsp;·&nbsp; "
                    f"◻️ Uncoverable/Untested: **{f.rules_uncoverable}** &nbsp;·&nbsp; "
                    f"🔍 Divergences: **{f.total_divergences}**"
                )
        st.divider()
        st.markdown("#### Rules whose status changed")
        prev_by_id = {row.rule_id: row for row in prev.facts.traceability}
        curr_by_id = {row.rule_id: row for row in result.facts.traceability}
        changed = []
        for rid, curr_row in curr_by_id.items():
            prev_row = prev_by_id.get(rid)
            if prev_row and prev_row.status != curr_row.status:
                changed.append({
                    "Rule": rid,
                    f"{prev_label}": STATUS_META.get(prev_row.status, {}).get("label", prev_row.status),
                    f"{curr_label}": STATUS_META.get(curr_row.status, {}).get("label", curr_row.status),
                })
        if changed:
            st.dataframe(pd.DataFrame(changed), use_container_width=True, hide_index=True)
        else:
            st.success("No rule changed status between these two runs.")

with tabs[3]:
    st.subheader("Run history (this session)")
    history = st.session_state.get("run_history", [])
    if not history:
        st.info("No runs recorded yet.")
    else:
        st.dataframe(pd.DataFrame(history), use_container_width=True, hide_index=True)
        st.caption(
            f"{len(history)} run(s) this session (this table clears on app restart, "
            f"but the 'Saved to' folders on disk under `runs/` do not — every run's "
            f"generated code, evidence pack, and trace stay there permanently)."
        )

with tabs[4]:
    st.subheader("Code paths no rule describes")
    if not facts.untraceable_findings:
        st.success("None found in this run's vector set.")
    for f in facts.untraceable_findings:
        st.warning(f"**{f.id}**: {f.description}")
        st.caption(f"Triggering vectors: {', '.join(f.triggering_vectors)}")

with tabs[5]:
    st.subheader("Change-approval evidence pack sections")
    for kind, text in result.sections.items():
        st.markdown(f"**{kind.replace('_', ' ').title()}**")
        st.write(text)

with tabs[6]:
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

with tabs[7]:
    st.subheader("Legacy code, business rules, and the AI-generated replacement")
    st.caption("Shown live from disk — the Java below is exactly what this run just "
               "compiled and tested, not a canned example.")

    root = Path(__file__).resolve().parent
    src_choice = st.radio(
        "Pick a file to view",
        [
            "🗄️ Legacy COBOL (data/src/legacy/INTCALC.cbl)",
            "📜 SME-approved rules (data/rules/validated_rules.yaml)",
            "☕ AI-generated modern code (generated/GeneratedIntcalc.java)",
        ],
        horizontal=False,
    )

    def show_source(path: Path, language: str):
        if not path.exists():
            st.warning(f"`{path.relative_to(root)}` not found yet — run the pipeline first.")
            return
        st.code(path.read_text(), language=language, line_numbers=True)

    if src_choice.startswith("🗄️"):
        show_source(root / "data" / "src" / "legacy" / "INTCALC.cbl", "cobol")
    elif src_choice.startswith("📜"):
        show_source(root / "data" / "rules" / "validated_rules.yaml", "yaml")
    else:
        show_source(root / "generated" / "GeneratedIntcalc.java", "java")
        st.caption("This file is regenerated fresh on every run and is intentionally "
                   "**not** committed to git — it's disposable AI output, not a trusted "
                   "static artifact. The legacy COBOL and the rules file, by contrast, "
                   "are permanent and version-controlled.")

with tabs[8]:
    st.write(f"HTML trace: `{result.trace_path}`")
    st.write(f"Evidence pack: `{result.evidence_path}`")
    st.write(f"Generated code: `{result.source.path}`")
    if last_save_dir:
        st.write(f"This run auto-saved to: `{last_save_dir}`")
    try:
        dl1, dl2, dl3 = st.columns(3)
        dl1.download_button("⬇ Download evidence pack (HTML)",
                             data=Path(result.evidence_path).read_bytes(),
                             file_name="evidence_pack.html", mime="text/html",
                             use_container_width=True)
        dl2.download_button("⬇ Download run trace (HTML)",
                             data=Path(result.trace_path).read_bytes(),
                             file_name=Path(result.trace_path).name, mime="text/html",
                             use_container_width=True)
        dl3.download_button("⬇ Download generated Java",
                             data=result.source.content.encode("utf-8"),
                             file_name=Path(result.source.path).name, mime="text/plain",
                             use_container_width=True)
    except Exception as exc:
        st.caption(f"(download unavailable: {exc})")

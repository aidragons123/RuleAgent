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

import csv
import datetime as _dt
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace as _dc_replace
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

import core.differential as _differential  # noqa: E402
import core.pipeline as _pipeline_mod  # noqa: E402
from ai.implementation import BUG_VARIANTS  # noqa: E402
from ai_platform.config import get_config  # noqa: E402
from ai_platform.tracer import Tracer as _Tracer  # noqa: E402
from core import cobol_runner as _cobol_runner  # noqa: E402
from core.harness import coverage_from_matrix  # noqa: E402
from core.java_runner import JavaGeneratedModule, JavaRunnerError  # noqa: E402
from core.pipeline import Pipeline, load_heldback_vectors, load_seed_vectors  # noqa: E402
from core.rules_loader import load_signature  # noqa: E402

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

    /* --------------------------------------------------- result scoreboard */
    .score-panel {
        background:#ffffff; border:1px solid #eaecef; border-radius:16px;
        border-top:5px solid var(--accent, #2a78d6);
        padding:1.15rem 1.35rem 1.25rem; height:100%;
        box-shadow:0 2px 10px rgba(20,36,58,.05);
    }
    .score-title {
        font-size:.74rem; font-weight:800; letter-spacing:.09em;
        text-transform:uppercase; color:#6b7280;
    }
    .score-headline { font-size:2.9rem; font-weight:800; color:#14243a; line-height:1.05; margin-top:.35rem; }
    .score-sub { font-size:.86rem; color:#5a6472; font-weight:600; }
    .score-bar {
        display:flex; width:100%; height:24px; border-radius:8px; overflow:hidden;
        background:#f0f0ee; border:1px solid #eaecef; margin:.85rem 0 .75rem;
    }
    .score-seg { height:100%; min-width:2px; border-right:2px solid #ffffff; }
    .score-seg:last-child { border-right:none; }
    .score-rows { display:flex; flex-direction:column; gap:.38rem; }
    .score-row { display:flex; align-items:center; gap:.5rem; font-size:.88rem; color:#3a4453; }
    .score-sw { width:12px; height:12px; border-radius:3px; flex:none; }
    .score-pct { font-weight:800; color:#14243a; min-width:3.6rem; text-align:right; }
    .score-lbl { flex:1; }
    .score-cnt { color:#8a94a1; font-size:.82rem; white-space:nowrap; }

    /* --------------------------------------------- collapsible sections */
    [data-testid="stExpander"] {
        border:1px solid #e8eaee !important; border-radius:14px !important;
        background:#ffffff !important; margin-bottom:1rem !important;
        box-shadow:0 1px 2px rgba(20,36,58,.04), 0 6px 18px rgba(20,36,58,.05) !important;
        overflow:hidden !important;
    }
    [data-testid="stExpander"] summary {
        font-weight:700 !important; font-size:.92rem !important;
        padding:.72rem 1rem !important; border-radius:14px !important;
    }
    [data-testid="stExpander"] summary:hover { background:#f7f8fa !important; }
    /* No per-state colour tint here: Streamlit gives expanders no hook to
       target an individual one, and the emoji + wording in each header
       already names the state. Colour would have been decoration anyway. */

    /* ------------------------------------------------ hero metric row */
    .hero-row { display:flex; gap:1rem; flex-wrap:wrap; margin-bottom:1.1rem; }
    .hero-card {
        flex:1 1 250px; background:#ffffff; border:1px solid #e8eaee;
        border-radius:18px; padding:1.15rem 1.3rem 1.25rem;
        box-shadow:0 1px 2px rgba(20,36,58,.04), 0 8px 24px rgba(20,36,58,.06);
        position:relative; overflow:hidden;
    }
    .hero-card::before {
        content:""; position:absolute; inset:0 0 auto 0; height:4px;
        background:linear-gradient(90deg, var(--a) 0%, var(--a) 60%, transparent 100%);
    }
    .hero-card.wide { flex:2 1 420px; }
    .hc-label {
        font-size:.7rem; font-weight:800; letter-spacing:.1em; text-transform:uppercase;
        color:#8a94a1; margin-bottom:.15rem;
    }
    .hc-sub { font-size:.83rem; color:#5a6472; line-height:1.45; }
    .hc-sub b { color:#14243a; }

    /* radial gauge — the single headline number, ring + value in the middle */
    .gauge-wrap { display:flex; justify-content:center; padding:.35rem 0 .5rem; }
    svg.gauge { width:158px; height:158px; display:block; }
    svg.gauge .g-track { fill:none; stroke:#eef0f3; }
    svg.gauge .g-val   { fill:none; transition:stroke-dasharray .5s ease; }
    svg.gauge .g-num {
        font-size:30px; font-weight:800; fill:#14243a; text-anchor:middle;
        font-family:-apple-system,Segoe UI,Roboto,sans-serif;
    }
    svg.gauge .g-cap {
        font-size:10.5px; font-weight:700; fill:#8a94a1; text-anchor:middle;
        letter-spacing:.09em; font-family:-apple-system,Segoe UI,Roboto,sans-serif;
    }

    /* composition bar — proportion of rule outcomes */
    .comp-bar {
        display:flex; height:30px; border-radius:9px; overflow:hidden;
        background:#f0f1f3; margin:.9rem 0 .85rem;
    }
    .comp-seg { height:100%; min-width:3px; border-right:2px solid #fff; position:relative; }
    .comp-seg:last-child { border-right:none; }
    .comp-legend { display:flex; flex-direction:column; gap:.45rem; }
    .comp-row { display:flex; align-items:center; gap:.55rem; font-size:.87rem; }
    .comp-sw { width:12px; height:12px; border-radius:3px; flex:none; }
    .comp-pct {
        font-weight:800; color:#14243a; min-width:3.5rem; text-align:right;
        font-variant-numeric:tabular-nums;
    }
    .comp-lbl { flex:1; color:#3a4453; }
    .comp-cnt { color:#8a94a1; font-size:.82rem; white-space:nowrap; }
    .comp-foot {
        display:flex; gap:.6rem; margin-top:1rem; padding-top:.85rem;
        border-top:1px solid #eef0f3;
    }
    .cf-item { flex:1; }
    .cf-num { font-size:1.25rem; font-weight:800; color:#14243a; line-height:1.2; }
    .cf-lbl { font-size:.74rem; color:#8a94a1; font-weight:600; }

    /* rule map — every rule in the scope, at a glance */
    .rule-map-wrap {
        background:#ffffff; border:1px solid #e8eaee; border-radius:18px;
        padding:1.05rem 1.25rem 1.2rem; margin-bottom:1.1rem;
        box-shadow:0 1px 2px rgba(20,36,58,.04), 0 8px 24px rgba(20,36,58,.06);
    }
    .rule-map { display:flex; flex-wrap:wrap; gap:.45rem; margin-top:.75rem; }
    .rm-chip {
        display:inline-flex; align-items:center; gap:.3rem; cursor:default;
        border:1px solid #e8eaee; border-left:4px solid var(--c);
        border-radius:8px; padding:.32rem .6rem; font-size:.79rem; font-weight:700;
        color:#14243a; background:#fcfcfd; transition:transform .12s ease, box-shadow .12s ease;
    }
    .rm-chip:hover { transform:translateY(-2px); box-shadow:0 4px 12px rgba(20,36,58,.12); }

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
        color: #000000 !important;
    }
    /* The open option list is rendered in a portal outside the sidebar */
    [data-baseweb="popover"] [role="listbox"],
    [data-baseweb="popover"] [role="listbox"] * {
        color: #000000 !important;
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


# ------------------------------------------------------------- fast path
# The differential step is what makes a run slow: core/differential.py walks
# the vectors one at a time, and each one launches a COBOL process (~55 ms)
# and a fresh JVM (~110 ms) — ~50 s for a 279-vector full run. core/ is
# write-locked (`make verify` checksums everything outside ai/), so the
# speed-ups live here instead. Three of them, none of which changes a single
# computed value:
#
#   1. The generated Java runs ALL vectors through ONE JVM (see the batch
#      runner below) instead of one JVM per vector.
#   2. The COBOL oracle cannot be batched — INTCALC.cbl does ACCEPT ...
#      STOP RUN, one line per process, and the file is checksum-locked — so
#      its outputs are memoised to disk instead, keyed by the hash of the
#      compiled binary. The values still come from real oracle runs; they
#      are just not recomputed once the same binary has already answered the
#      same input. A rebuilt INTCALC.cbl changes the hash and voids the file.
#   3. javac is memoised on the source hash, so re-running the same variant
#      skips the compile.
#
# Everything is keyed on the hash of the artefact that produced it, so a
# bug-injected variant can never be served a clean variant's answers.
_WORKERS = min(16, (os.cpu_count() or 4) * 2)
_REPO_ROOT = Path(__file__).resolve().parent
_CACHE_DIR = _REPO_ROOT / "out"
# One subdirectory per generated-source hash, so two variants never share
# (and never overwrite) each other's .class files.
_BUILD_ROOT = _REPO_ROOT / "generated" / "javabuild"

# Wrapper that drives the AI-generated class over the same pipe-delimited
# wire protocol, in one JVM. It does not modify (or subclass, or reach into)
# the generated class: it calls the same static compute(String[]) entry point
# main() calls, once per input line. GeneratedIntcalc holds no mutable static
# state — every field it declares is `static final` — so vectors cannot leak
# into each other; this is the same isolation the per-vector JVM gave.
_BATCH_RUNNER = """
import java.io.BufferedReader;
import java.io.InputStreamReader;

public class BatchRunner {
    public static void main(String[] args) throws Exception {
        BufferedReader reader = new BufferedReader(new InputStreamReader(System.in));
        StringBuilder out = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) {
            if (line.isEmpty()) continue;
            try {
                String[] result = GeneratedIntcalc.compute(line.split("\\\\|", -1));
                out.append("OK\\t").append(String.join("|", result)).append('\\n');
            } catch (Throwable t) {
                // Mirrors the per-vector runner: one bad vector must not
                // take down the rest of the batch.
                out.append("ERR\\t").append(t).append('\\n');
            }
        }
        System.out.print(out);
    }
}
"""


def _digest(*chunks: bytes) -> str:
    h = hashlib.sha256()
    for c in chunks:
        h.update(c)
    return h.hexdigest()[:16]


def _load_disk_cache(name: str) -> dict:
    path = _CACHE_DIR / f".cache_{name}.json"
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}  # missing or corrupt cache is never fatal — just recompute


def _save_disk_cache(name: str, data: dict) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (_CACHE_DIR / f".cache_{name}.json").write_text(json.dumps(data))
    except Exception:
        pass  # a cache we cannot persist is a slow run, not a broken one


def _install_fast_differential() -> None:
    if getattr(_pipeline_mod.run_differential, "_fast", False):
        return  # already installed in this server process

    original_oracle = _differential.run_oracle
    original_differential = _pipeline_mod.run_differential

    oracle_memo: dict = {}          # {binary_hash: {wire_line: output_dict}}
    java_memo: dict = {}            # {class_hash:  {wire_line: output_dict}}
    compiled: dict = {}             # {source_hash: build_dir}
    lock = threading.Lock()

    # ---------------------------------------------------------- COBOL side
    def oracle_bucket() -> tuple[str, dict]:
        binary = _cobol_runner.ensure_compiled()   # rebuilds if INTCALC.cbl changed
        key = _digest(binary.read_bytes())
        if key not in oracle_memo:
            with lock:
                oracle_memo[key] = _load_disk_cache(f"oracle_{key}")
        return key, oracle_memo[key]

    def cached_oracle(vector_input, sig):
        key, bucket = oracle_bucket()
        line = _cobol_runner.encode_input(vector_input, sig)
        hit = bucket.get(line)
        if hit is None:
            hit = original_oracle(vector_input, sig)
            with lock:
                bucket[line] = hit
        return dict(hit)

    def fill_oracle(vectors, sig) -> None:
        """Runs the real oracle for every input not already memoised. One
        process per vector is unavoidable here, so they run concurrently."""
        key, bucket = oracle_bucket()
        missing = {_cobol_runner.encode_input(v.input, sig): v.input
                   for v in vectors if _cobol_runner.encode_input(v.input, sig) not in bucket}
        if not missing:
            return
        with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            results = pool.map(lambda i: original_oracle(i, sig), missing.values())
            for line, out in zip(missing, results):
                bucket[line] = out
        _save_disk_cache(f"oracle_{key}", bucket)

    # ----------------------------------------------------------- Java side
    def cached_compile(source):
        """Compiles each distinct generated source into its OWN build dir,
        keyed by the hash of that source.

        core/java_runner.py deliberately recompiles on every call so that a
        bug-injected variant can never be served from a stale .class file.
        Caching the compile WITHOUT also separating the output directories
        reintroduces exactly that hazard: every variant writes into one
        shared generated/javabuild/, so a cache hit can hand back a
        directory that a different variant has since overwritten — the
        clean run then silently answers with flawed classes. Per-variant
        directories keep the caching and the guarantee."""
        key = _digest(source.content.encode())

        # Always refresh the canonical .java on disk: the "Data & source"
        # tab reads it, and it must show the variant that just ran.
        java_file = _REPO_ROOT / source.path
        java_file.parent.mkdir(parents=True, exist_ok=True)
        java_file.write_text(source.content)

        if key not in compiled:
            build_dir = _BUILD_ROOT / key
            build_dir.mkdir(parents=True, exist_ok=True)
            runner = build_dir / "BatchRunner.java"
            runner.write_text(_BATCH_RUNNER)
            proc = subprocess.run(
                ["javac", "-d", str(build_dir), str(java_file), str(runner)],
                capture_output=True, text=True,
            )
            if proc.returncode != 0:
                raise JavaRunnerError(
                    f"javac failed for {java_file}:\n{proc.stdout}\n{proc.stderr}"
                )
            compiled[key] = build_dir
        return compiled[key]

    def java_bucket(module) -> tuple[str, dict]:
        classes = sorted(Path(module.build_dir).glob("*.class"))
        key = _digest(*(p.read_bytes() for p in classes))
        if key not in java_memo:
            java_memo[key] = _load_disk_cache(f"java_{key}")
        return key, java_memo[key]

    def fill_java(vectors, module, sig) -> dict:
        """Feeds every not-yet-memoised vector through ONE JVM, over the
        same wire protocol the per-vector runner used."""
        key, bucket = java_bucket(module)
        missing = [line for line in
                   dict.fromkeys(_cobol_runner.encode_input(v.input, sig) for v in vectors)
                   if line not in bucket]
        if missing:
            proc = subprocess.run(
                ["java", "-cp", str(module.build_dir), "BatchRunner"],
                input="\n".join(missing) + "\n", capture_output=True, text=True,
            )
            if proc.returncode != 0:
                raise JavaRunnerError(f"batch java run failed:\n{proc.stderr}")
            replies = [ln for ln in proc.stdout.splitlines() if ln]
            if len(replies) != len(missing):
                raise JavaRunnerError(
                    f"batch java returned {len(replies)} lines for {len(missing)} vectors"
                )
            for line, reply in zip(missing, replies):
                status, _, payload = reply.partition("\t")
                bucket[line] = (_cobol_runner.decode_output(payload, sig)
                                if status == "OK" else {"__error__": payload})
            _save_disk_cache(f"java_{key}", bucket)
        return bucket

    class MemoisedJava:
        """Serves the batch's answers through the same .compute(dict) -> dict
        surface core/differential.py already calls."""

        def __init__(self, bucket: dict, sig):
            self.bucket = bucket
            self.sig = sig

        def compute(self, input_dict):
            out = self.bucket[_cobol_runner.encode_input(input_dict, self.sig)]
            if "__error__" in out:
                # core/differential.py catches this and records every output
                # field as divergent, exactly as it did per-vector.
                raise JavaRunnerError(out["__error__"])
            return dict(out)

    # ------------------------------------------------------------ the swap
    def fast_differential(vectors, module, sig):
        if not isinstance(module, JavaGeneratedModule):
            return original_differential(vectors, module, sig)
        fill_oracle(vectors, sig)
        bucket = fill_java(vectors, module, sig)
        # core/differential.py then runs its own loop and its own comparison
        # over pre-computed values — the divergence logic stays untouched.
        return original_differential(vectors, MemoisedJava(bucket, sig), sig)

    fast_differential._fast = True
    fast_differential._fill_oracle = fill_oracle
    _differential.run_oracle = cached_oracle
    _differential.compile_java = cached_compile
    _pipeline_mod.load_generated = _differential.load_generated
    _pipeline_mod.run_differential = fast_differential


_prewarm_started = False


def _prewarm() -> None:
    """Builds the oracle cache for the shipped vectors in the background, so
    the first click lands on a warm cache instead of paying for 230 COBOL
    processes. Starts at page load (not at click time, which would be too
    late to help), runs once per server, and never blocks the page."""
    global _prewarm_started
    if _prewarm_started:
        return
    _prewarm_started = True

    def work():
        try:
            _pipeline_mod.run_differential._fill_oracle(
                load_seed_vectors() + load_heldback_vectors(), load_signature())
        except Exception:
            pass  # a failed pre-warm only means the first run is slower

    threading.Thread(target=work, daemon=True).start()


def _install_lazy_trace_flush() -> None:
    """Tracer rewrites the whole HTML trace after every recorded event, and
    each rewrite re-renders every prior event, so a full run spends most of
    its time (O(n^2)) re-writing the same file. Write it at start and at
    finalize() instead; the finished trace has the same content."""
    if getattr(_Tracer._flush, "_lazy", False):
        return
    original_flush = _Tracer._flush

    def lazy_flush(self):
        if self.steps and not self.summary:  # mid-run: finalize() writes it out
            return
        original_flush(self)

    lazy_flush._lazy = True
    _Tracer._flush = lazy_flush


_install_fast_differential()
_install_lazy_trace_flush()
_prewarm()       # at page load, so the cache is filling while the user reads


@st.cache_resource
def get_pipeline() -> Pipeline:
    return Pipeline()


COBOL_SOURCE_PATH = Path(__file__).resolve().parent / "data" / "src" / "legacy" / "INTCALC.cbl"
COBOL_BACKUP_DIR = Path(__file__).resolve().parent / "runs" / "cobol_backups"


def _to_raw_github_url(url: str) -> str:
    """Convert a github.com/.../blob/... URL to its raw.githubusercontent.com
    equivalent, so pasting the ordinary browser link (what someone would
    actually copy) works, not just an already-raw URL."""
    m = re.match(r"^https://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)$", url.strip())
    if m:
        user, repo, branch, path = m.groups()
        return f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/{path}"
    return url.strip()


def fetch_cobol_source(url: str, timeout: int = 15) -> str:
    raw_url = _to_raw_github_url(url)
    req = urllib.request.Request(raw_url, headers={"User-Agent": "CodeVerus-demo"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return data.decode("utf-8", errors="replace")


# The happy flow is the clean path: the rules this implementation satisfies
# EXACTLY — every one validated against the real COBOL oracle, zero
# divergence, nothing left untested. Scoping the run to them is what makes
# it a happy flow, rather than hiding the rules that fail.
#
# The list is deliberately explicit rather than "whatever happened to pass
# this time": if a future change breaks one of these, the scope reports it
# as INVALIDATED instead of quietly dropping it from the demo.
HAPPY_FLOW_RULES = ["R-002", "R-005", "R-006", "R-010", "R-011",
                    "R-012", "R-013", "R-019", "R-022"]


def scope_matrix(result, rule_ids: list[str]):
    """Restricts a result's traceability matrix — and the counts derived
    from it — to the rules the scope is actually about.

    core/pipeline.py always builds the matrix over all 24 rules, so a
    9-rule scope would otherwise report the other 15 as UNTESTED. The
    counting itself is delegated to core.harness.coverage_from_matrix, so
    the UI never reimplements how a status maps to a bucket."""
    rows = [r for r in result.facts.traceability if r.rule_id in rule_ids]
    cov = coverage_from_matrix(rows)
    facts = result.facts.model_copy(update={
        "traceability": rows,
        "total_rules": cov.total_rules,
        "rules_validated": cov.validated,
        "rules_invalidated": cov.invalidated,
        "rules_uncoverable": cov.uncoverable + cov.untested,
    })
    return _dc_replace(result, facts=facts)


def exercised_rules(result) -> list[str]:
    """The rules a run actually exercised — those with at least one citing
    test vector. The pipeline always builds the matrix over all 24 rules,
    so scoping to these is what keeps the untouched ones from showing up as
    UNTESTED noise in a deliberately narrow scope."""
    return [r.rule_id for r in result.facts.traceability if r.tests]


@contextmanager
def injected_bug(bug: str | None):
    """Runs the block with UC04_INJECT_BUG set, then restores whatever was
    there before. ai/implementation.py reads it when it generates the Java,
    so this is what makes a scope run against deliberately flawed code."""
    previous = os.environ.get("UC04_INJECT_BUG")
    if bug:
        os.environ["UC04_INJECT_BUG"] = bug
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("UC04_INJECT_BUG", None)
        else:
            os.environ["UC04_INJECT_BUG"] = previous


def run_scope(scope: str):
    pipeline = get_pipeline()
    heldback = load_heldback_vectors()
    seed = load_seed_vectors()

    if scope == "Full run (all 24 rules, all vectors)":
        return pipeline.run(include_synthesised=True, extra_vectors=seed + heldback,
                             run_id="ui-full")
    if scope == "Happy flow (clean path)":
        # Synthesise vectors for the in-scope rules only, then narrow the
        # matrix to them: 20 vectors, 0 divergences, 9 of 9 validated.
        result = pipeline.run(include_synthesised=True, extra_vectors=[], run_id="ui-happy",
                               synthesis_rule_ids=HAPPY_FLOW_RULES)
        return scope_matrix(result, HAPPY_FLOW_RULES)
    if scope == "Rounding flaw (R-009)":
        # The negative counterpart to the happy flow: regenerate the Java
        # with a real rounding defect in it, then run R-009's own vectors
        # plus the seed set so the damage is visible across many inputs.
        with injected_bug("rounding_mode"):
            result = pipeline.run(include_synthesised=True, extra_vectors=seed,
                                   run_id="ui-rounding", synthesis_rule_ids=["R-009"])
        return scope_matrix(result, exercised_rules(result))
    if scope == "Untraceable cap behaviour":
        # Clean code, but only the vectors that trip the undocumented
        # interest cap — so what is left is the behaviour no rule explains.
        cap_vectors = [v for v in heldback if "cap" in v.note.lower()]
        result = pipeline.run(include_synthesised=False, extra_vectors=cap_vectors,
                               run_id="ui-untraceable")
        return scope_matrix(result, exercised_rules(result))
    raise ValueError(scope)


# ---------------------------------------------------------- CSV report
def build_csv_report(result, scope_label: str, bug: str | None) -> str:
    """Flattens a run into one CSV report: a summary block, then the
    rule-by-rule verdicts, then every divergence, then any untraceable
    findings. Written as labelled sections rather than one wide table so
    it stays readable when opened straight in Excel."""
    facts = result.facts
    diverged = {d.vector_id for d in result.divergences}
    matched = facts.total_vectors - len(diverged)
    judged = facts.rules_validated + facts.rules_invalidated

    def p(n, total):
        return f"{n / total * 100:.1f}%" if total else "n/a"

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")

    w.writerow(["CodeVerus - pipeline report"])
    w.writerow(["Generated", _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    w.writerow(["Scope", scope_label])
    w.writerow(["Generated code", f"flawed on purpose ({bug})" if bug else "clean"])
    w.writerow([])

    w.writerow(["SUMMARY"])
    w.writerow(["Metric", "Count", "Percent"])
    w.writerow(["Rules in scope", facts.total_rules, ""])
    w.writerow(["Succeeded - validated flawless", facts.rules_validated,
                p(facts.rules_validated, facts.total_rules)])
    w.writerow(["Failed - flaw found", facts.rules_invalidated,
                p(facts.rules_invalidated, facts.total_rules)])
    w.writerow(["Not testable - uncoverable/untested", facts.rules_uncoverable,
                p(facts.rules_uncoverable, facts.total_rules)])
    w.writerow(["Pass rate (judgeable rules only)", judged, p(facts.rules_validated, judged)])
    w.writerow(["Test vectors executed", facts.total_vectors, ""])
    w.writerow(["Vectors matching the oracle", matched, p(matched, facts.total_vectors)])
    w.writerow(["Vectors diverged", len(diverged), p(len(diverged), facts.total_vectors)])
    w.writerow(["Field-level divergence records", facts.total_divergences, ""])
    w.writerow(["Untraceable-behaviour findings", len(facts.untraceable_findings), ""])
    w.writerow([])

    w.writerow(["RULE-BY-RULE VERDICT"])
    w.writerow(["Rule ID", "Status", "Status meaning", "Flaw side",
                "Citing tests", "Citing code paths", "Statement"])
    for row in facts.traceability:
        meta = STATUS_META.get(row.status, {})
        w.writerow([row.rule_id, row.status, meta.get("label", ""), row.flaw_side,
                    len(row.tests), "; ".join(row.code_citations),
                    " ".join(row.statement.split())])
    w.writerow([])

    w.writerow(["DIVERGENCES (COBOL oracle vs generated Java)"])
    w.writerow(["Vector ID", "Field", "COBOL expected", "Java actual", "Rule IDs"])
    for d in result.divergences:
        w.writerow([d.vector_id, d.field, d.expected, d.actual, "; ".join(d.rule_ids)])
    w.writerow([])

    w.writerow(["DIAGNOSES"])
    w.writerow(["Vector ID", "Field", "Cause", "Explanation", "Suggested fix"])
    for d in result.diagnoses:
        w.writerow([d.vector_id, d.field, d.cause,
                    " ".join(d.explanation.split()),
                    " ".join((d.fix_suggested or "").split())])
    w.writerow([])

    w.writerow(["UNTRACEABLE-BEHAVIOUR FINDINGS"])
    w.writerow(["ID", "Description", "Triggering vectors"])
    for f in facts.untraceable_findings:
        w.writerow([f.id, " ".join(f.description.split()), "; ".join(f.triggering_vectors)])

    return buf.getvalue()


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
        "value": "Happy flow (clean path)",
        "help": "The 9 rules this implementation satisfies exactly — all validated, "
                "nothing invalidated, nothing untested.",
    },
    "Rounding flaw": {
        "value": "Rounding flaw (R-009)",
        "help": "Regenerates the Java with a real rounding defect — interest truncated to "
                "whole dollars — and runs it. Expect R-009 INVALIDATED, flaw side: code.",
        "bug": "rounding_mode",
    },
    "Untraceable cap behaviour": {
        "value": "Untraceable cap behaviour",
        "help": "Clean code, run only on the vectors that trip the undocumented interest "
                "cap — the behaviour no rule describes.",
    },
}

with st.sidebar:
    st.markdown("## CodeVerus")
    st.caption("AI COBOL modernization & rule validation")
    st.write("")

    with st.container(border=True):
        st.markdown("#### Load legacy COBOL source (optional)")
        current_source_url = st.session_state.get("cobol_source_url")
        if current_source_url:
            st.caption(f"→ Currently validating against code loaded from: {current_source_url}")
        else:
            st.caption("→ Currently validating against the bundled "
                       "`data/src/legacy/INTCALC.cbl`.")
        github_url = st.text_input(
            "GitHub URL (page link or raw link)", key="github_cobol_url",
            placeholder="https://github.com/org/repo/blob/main/INTCALC.cbl",
            label_visibility="collapsed",
        )
        load_cobol_clicked = st.button(
            "⬇  Load COBOL from GitHub", use_container_width=True,
        )
        st.caption("Overwrites the local COBOL file and recompiles automatically on "
                   "the next Run pipeline click. The rules and I/O spec below still "
                   "describe INTCALC specifically — this is for pulling a different "
                   "*revision* of the same program, not an unrelated one.")

    with st.container(border=True):
        st.markdown("#### Choose what to test")
        scope_key = st.selectbox(
            "Scope", list(SCOPE_OPTIONS.keys()), label_visibility="collapsed",
        )
        scope = SCOPE_OPTIONS[scope_key]["value"]
        st.caption(SCOPE_OPTIONS[scope_key]["help"])

    run_clicked = st.button("▶  Run pipeline", type="primary", use_container_width=True)

    prior_result = st.session_state.get("result")
    with st.container(border=True):
        st.markdown("#### Modify a rule & re-validate")
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

# There is no code-variant picker any more: the scope decides whether the
# run uses clean or deliberately flawed code (run_scope injects it), and
# UC04_INJECT_BUG set before launch still applies to the scopes that don't.
bug = SCOPE_OPTIONS[scope_key].get("bug") or os.environ.get("UC04_INJECT_BUG")


if load_cobol_clicked:
    if not github_url.strip():
        st.warning("Paste a GitHub URL first.")
    else:
        try:
            with st.spinner("Fetching COBOL source from GitHub..."):
                content = fetch_cobol_source(github_url)
            if not content.strip():
                st.error("Fetched file is empty — check the URL.")
            else:
                COBOL_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
                if COBOL_SOURCE_PATH.exists():
                    backup_path = COBOL_BACKUP_DIR / (
                        f"INTCALC_{_dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.cbl.bak"
                    )
                    backup_path.write_text(COBOL_SOURCE_PATH.read_text())
                COBOL_SOURCE_PATH.write_text(content)
                st.session_state["cobol_source_url"] = github_url.strip()
                st.success(
                    f"Loaded {len(content)} characters from GitHub into "
                    f"`data/src/legacy/INTCALC.cbl`. Click **Run pipeline** to "
                    f"recompile it and validate against it."
                )
                with st.expander("Preview fetched source"):
                    st.code(content[:3000], language="cobol")
        except urllib.error.HTTPError as exc:
            st.error(f"GitHub returned an error ({exc.code}) — check the URL is public and correct.")
        except urllib.error.URLError as exc:
            st.error(f"Couldn't reach GitHub from this environment: {exc.reason}")
        except Exception as exc:
            st.error(f"Failed to load COBOL source: {exc}")

# There is no code-variant picker any more: the scope decides whether the
# run uses clean or deliberately flawed code (run_scope injects it), and
# UC04_INJECT_BUG set before launch still applies to the scopes that don't.
bug = SCOPE_OPTIONS[scope_key].get("bug") or os.environ.get("UC04_INJECT_BUG")

if run_clicked:
    # Keep the run this button-click is about to replace, so a "compare
    # with previous run" view is possible without re-running anything.
    if st.session_state.get("result") is not None:
        st.session_state["prev_result"] = st.session_state["result"]
        st.session_state["prev_label"] = st.session_state.get("run_label", "previous run")

    with st.spinner(f"Running: {scope}..."):
        new_result = run_scope(scope)
        st.session_state["result"] = new_result
        st.session_state["scope"] = scope
        st.session_state["scope_key"] = scope_key   # drives the default rule filter
        st.session_state["bug"] = bug
        st.session_state["rule_change"] = None
        run_label = f"{scope_key} · {_dt.datetime.now():%H:%M:%S}"
        st.session_state["run_label"] = run_label

    _f = new_result.facts
    _judged = _f.rules_validated + _f.rules_invalidated
    _all = _judged + _f.rules_uncoverable
    _diverged = len({d.vector_id for d in new_result.divergences})
    _now = _dt.datetime.now()
    # The report is built HERE, from this run's own result, and kept with the
    # history entry. That is what makes every past run individually
    # downloadable: a later run replaces st.session_state["result"], but each
    # entry already holds its own finished CSV, so it can never be
    # regenerated from — or confused with — a different run's numbers.
    st.session_state.setdefault("run_history", []).append({
        "Time": _now.strftime("%H:%M:%S"),
        "Scope": scope_key,
        "Pass rate": f"{_f.rules_validated / _judged * 100:.1f}%" if _judged else "—",
        "Succeeded": _f.rules_validated,
        "Failed": _f.rules_invalidated,
        "Not testable": _f.rules_uncoverable,
        "Vectors matched": f"{(_f.total_vectors - _diverged) / _f.total_vectors * 100:.1f}%"
                            if _f.total_vectors else "—",
        "Divergences": _f.total_divergences,
        # not shown in the table - carried for the per-run download buttons
        "_csv": build_csv_report(new_result, scope_key, bug),
        "_filename": f"codeverus_report_{scope_key.lower().replace(' ', '_')}"
                     f"_{_now:%Y%m%d_%H%M%S}.csv",
        "_trace": str(new_result.trace_path),
        "_bug": bug,
    })
    # Rerun once so the sidebar's "Modify a rule & re-validate" section (which
    # reads the just-saved result) reflects it immediately, instead of one
    # click later.
    st.rerun()

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
        with st.spinner(f"Regenerating the implementation from the new wording of {rule_change_id}..."):
            new_result = get_pipeline().modify_rule_and_revalidate(
                rule_change_id, rule_change_text.strip(), prior.vectors, run_id="ui-rule-change",
            )
        st.session_state["result"] = new_result
        st.session_state["bug"] = None
        st.session_state["rule_change"] = {
            "rule_id": rule_change_id, "old_statement": old_statement,
            "new_statement": rule_change_text.strip(),
            "mock_mode": os.environ.get("UC04_LLM_MODE", get_config()["llm"]["mode"]) != "real",
        }
        run_label = f"{st.session_state.get('run_label', 'previous run')} · rule changed: {rule_change_id}"
        st.session_state["run_label"] = run_label

        _f = new_result.facts
        _judged = _f.rules_validated + _f.rules_invalidated
        _diverged = len({d.vector_id for d in new_result.divergences})
        _now = _dt.datetime.now()
        st.session_state.setdefault("run_history", []).append({
            "Time": _now.strftime("%H:%M:%S"),
            "Scope": f"Rule changed: {rule_change_id}",
            "Pass rate": f"{_f.rules_validated / _judged * 100:.1f}%" if _judged else "—",
            "Succeeded": _f.rules_validated,
            "Failed": _f.rules_invalidated,
            "Not testable": _f.rules_uncoverable,
            "Vectors matched": f"{(_f.total_vectors - _diverged) / _f.total_vectors * 100:.1f}%"
                                if _f.total_vectors else "—",
            "Divergences": _f.total_divergences,
            "_csv": build_csv_report(new_result, f"Rule changed: {rule_change_id}", None),
            "_filename": f"codeverus_report_rule_change_{rule_change_id.lower()}"
                         f"_{_now:%Y%m%d_%H%M%S}.csv",
            "_trace": str(new_result.trace_path),
            "_bug": None,
        })

result = st.session_state.get("result")

if result is None:
    st.info("👈 Choose a scope in the sidebar, then click **Run pipeline**.")
    st.stop()

facts = result.facts
active_bug = st.session_state.get("bug")
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
elif active_bug:
    v = BUG_VARIANTS[active_bug]
    st.error(
        f"🐞 **Flawed code generated on purpose — `{active_bug}`:** {v['description']} "
        f"The Java was regenerated with this defect, compiled, and run against the real "
        f"COBOL oracle. Expect **{v['rule_id']}** to show INVALIDATED below (flaw side: code)."
    )
else:
    st.success("✅ **Clean generated code** — no bug injected. Any divergence below "
               "is a genuine ambiguous-rule, rounding, or untraceable-behaviour finding, "
               "not an implementation defect.")

# The untraceable scope's whole point is these findings, so they lead rather
# than sitting three tabs away.
if facts.untraceable_findings:
    st.warning(
        f"🕵️ **{len(facts.untraceable_findings)} untraceable-behaviour finding(s)** — the COBOL "
        f"oracle does something no rule in `validated_rules.yaml` describes. The generated code "
        f"correctly refused to guess at it, which is why these rules read UNCOVERABLE rather "
        f"than being quietly 'fixed' to match. Detail in **🔬 Divergences & findings**."
    )

# ------------------------------------------------------------ scoreboard
# Two panels, two different denominators, both stated as percentages:
#   - rules   : how the 24 SME rules came out (the business answer)
#   - vectors : how many executed tests matched the oracle (the run answer)
# They are deliberately kept apart — a rule is not a test, and one rule can
# be exercised by many vectors, so mixing them into one "pass rate" would be
# a meaningless number.
def _pct(n: int, total: int) -> float:
    return (n / total * 100) if total else 0.0


# ---- axis 1: the 24 business rules
n_rules = facts.rules_validated + facts.rules_invalidated + facts.rules_uncoverable
n_ok, n_bad, n_na = facts.rules_validated, facts.rules_invalidated, facts.rules_uncoverable
n_testable = n_ok + n_bad          # rules this module can actually be judged on

# ---- axis 2: the test vectors actually executed
diverged_ids = {d.vector_id for d in result.divergences}
n_vec = facts.total_vectors
n_vec_bad = len(diverged_ids)
n_vec_ok = n_vec - n_vec_bad

c_ok = STATUS_META["VALIDATED"]["border"]
c_bad = STATUS_META["INVALIDATED_DEFECT"]["border"]
c_na = STATUS_META["UNCOVERABLE"]["border"]


def gauge_card(label: str, value: float | None, color: str, cap: str, sub: str) -> str:
    """A single headline percentage as a radial gauge. The number is printed
    in the middle, so the ring is reinforcement rather than the only way to
    read the value — colour alone never carries the result.

    value=None means "no such rate here" and draws an empty ring reading
    n/a. That is not the same as 0%: a scope where nothing is judgeable has
    no pass rate, and showing 0% would read as "everything failed"."""
    r, sw = 66, 13
    circ = 2 * math.pi * r
    if value is None:
        return f"""
    <div class="hero-card" style="--a:#c9ced6">
      <div class="hc-label">{label}</div>
      <div class="gauge-wrap">
        <svg class="gauge" viewBox="0 0 160 160" role="img" aria-label="{label}: not applicable">
          <title>{label}: not applicable — {sub}</title>
          <circle class="g-track" cx="80" cy="80" r="{r}" stroke-width="{sw}"/>
          <text class="g-num" x="80" y="80" style="fill:#9aa3b0">n/a</text>
          <text class="g-cap" x="80" y="99">{cap}</text>
        </svg>
      </div>
      <div class="hc-sub">{sub}</div>
    </div>"""
    dash = max(0.0, min(100.0, value)) / 100 * circ
    return f"""
    <div class="hero-card" style="--a:{color}">
      <div class="hc-label">{label}</div>
      <div class="gauge-wrap">
        <svg class="gauge" viewBox="0 0 160 160" role="img"
             aria-label="{label}: {value:.1f} percent. {sub}">
          <title>{label}: {value:.1f}% — {sub}</title>
          <circle class="g-track" cx="80" cy="80" r="{r}" stroke-width="{sw}"/>
          <circle class="g-val" cx="80" cy="80" r="{r}" stroke-width="{sw}"
                  stroke="{color}" stroke-linecap="round"
                  stroke-dasharray="{dash:.2f} {circ:.2f}"
                  transform="rotate(-90 80 80)"/>
          <text class="g-num" x="80" y="80">{value:.1f}%</text>
          <text class="g-cap" x="80" y="99">{cap}</text>
        </svg>
      </div>
      <div class="hc-sub">{sub}</div>
    </div>"""


def composition_card(label: str, rows: list[tuple[str, str, str, int, float]],
                     footer: list[tuple[str, str]]) -> str:
    """Proportion bar + legend. rows: (colour, icon, label, count, pct).
    Every segment is repeated in the legend with its icon, name, percentage
    and count — required here, because validated-green and defect-red are
    close enough under deuteranopia that colour alone would not separate
    'passed' from 'failed'."""
    segs = "".join(
        f'<div class="comp-seg" style="width:{pc:.3f}%;background:{col}" '
        f'title="{lbl}: {n} ({pc:.1f}%)"></div>'
        for col, ic, lbl, n, pc in rows if pc > 0
    )
    legend = "".join(
        f'<div class="comp-row"><span class="comp-sw" style="background:{col}"></span>'
        f'<span class="comp-pct">{pc:.1f}%</span>'
        f'<span class="comp-lbl">{ic} {lbl}</span>'
        f'<span class="comp-cnt">{n} rules</span></div>'
        for col, ic, lbl, n, pc in rows
    )
    foot = "".join(
        f'<div class="cf-item"><div class="cf-num">{num}</div>'
        f'<div class="cf-lbl">{lbl}</div></div>'
        for num, lbl in footer
    )
    return f"""
    <div class="hero-card wide" style="--a:{ACCENT_NEUTRAL}">
      <div class="hc-label">{label}</div>
      <div class="comp-bar">{segs}</div>
      <div class="comp-legend">{legend}</div>
      <div class="comp-foot">{foot}</div>
    </div>"""


st.markdown(
    '<div class="hero-row">'
    + gauge_card(
        "Pass rate · judgeable rules",
        _pct(n_ok, n_testable) if n_testable else None, c_ok, "PASSED",
        (f"<b>{n_ok} passed</b> / {n_bad} failed of the {n_testable} rules with both a "
         f"test and a code path."
         + (f" {n_na} more cannot be judged from this module's output." if n_na else ""))
        if n_testable else
        f"<b>None of these {n_rules} rules is independently judgeable</b> from this "
        f"module's output, so there is no pass rate to report — not a rate of zero.",
    )
    + gauge_card(
        "Vectors matching the oracle",
        _pct(n_vec_ok, n_vec), ACCENT_NEUTRAL, "MATCHED",
        f"<b>{n_vec_ok} of {n_vec} vectors</b> produced output identical to the compiled "
        f"COBOL oracle · {facts.total_divergences} field-level divergences.",
    )
    + composition_card(
        f"Rule outcomes · {n_rules} in scope",
        [(c_ok, "✅", "Succeeded — validated flawless", n_ok, _pct(n_ok, n_rules)),
         (c_bad, "❌", "Failed — flaw found", n_bad, _pct(n_bad, n_rules)),
         (c_na, "◻️", "Not testable — uncoverable / untested", n_na, _pct(n_na, n_rules))],
        [(f"{n_vec:,}", "test vectors executed"),
         (f"{n_vec_bad:,}", "vectors diverged"),
         (f"{facts.total_divergences:,}", "field divergences"),
         (f"{len(facts.untraceable_findings)}", "untraceable findings")],
    )
    + "</div>",
    unsafe_allow_html=True,
)

# A scope narrower than the whole rule file must say so, so a 100% score is
# never read as "all 24 rules pass".
if st.session_state.get("scope_key") != "Full run" and n_rules < 24:
    st.info(
        f"**Scope: {st.session_state.get('scope_key')}** — these percentages cover the "
        f"{n_rules} rules in this scope, not all 24. Choose **Full run** in the sidebar "
        f"for the complete picture."
    )

# Rule map: the whole scope on one line of sight. Hover any chip for its
# verdict and the rule text.
chips = "".join(
    f'<span class="rm-chip" style="--c:{STATUS_META[r.status]["border"]}" '
    f'title="{r.rule_id} — {STATUS_META[r.status]["label"]} (flaw side: {r.flaw_side})'
    f'&#10;&#10;{" ".join(r.statement.split())}">'
    f'{r.rule_id} {STATUS_META[r.status]["icon"]}</span>'
    for r in facts.traceability
)
st.markdown(
    f'<div class="rule-map-wrap">'
    f'<div class="hc-label">Rule map · hover any rule for its verdict</div>'
    f'<div class="rule-map">{chips}</div></div>',
    unsafe_allow_html=True,
)

status_counts = pd.Series([row.status for row in facts.traceability]).value_counts()
# Nothing to break down on a fully clean scope — don't offer an empty toggle.
if n_bad or n_na:
    with st.expander(f"Breakdown of the {n_bad} failures and {n_na} not-testable rules"):
        brk = [{"Status": f"{STATUS_META[s]['icon']} {STATUS_META[s]['label']}",
                "Rules": int(status_counts.get(s, 0)),
                "% of all rules": f"{_pct(int(status_counts.get(s, 0)), n_rules):.1f}%",
                "Rules affected": ", ".join(r.rule_id for r in facts.traceability
                                            if r.status == s) or "—"}
               for s in STATUS_ORDER if int(status_counts.get(s, 0)) > 0]
        st.dataframe(pd.DataFrame(brk), use_container_width=True, hide_index=True)
        st.caption(
            f"{facts.total_divergences} field-level divergence records across "
            f"{n_vec_bad} diverging vectors — one record per (vector, field) pair, so a "
            f"vector that disagrees on two fields counts twice."
        )

st.write("")

tabs = st.tabs(["✅ Rule results", "🔬 Divergences & findings", "📄 Evidence pack",
                "🧾 Data & source", "🕘 History & downloads"])

with tabs[0]:
    # No per-scope default filter: each scope's matrix already contains
    # exactly the rules that scope is about, so nothing needs hiding.
    ran_scope = st.session_state.get("scope_key", "")
    st.subheader("Every rule in this scope")
    status_filter = st.multiselect(
        "Filter by status", options=sorted(STATUS_LABELS, key=lambda k: k),
        format_func=lambda k: STATUS_LABELS[k], default=[],
        key=f"status_filter::{ran_scope}",
    )
    rows = facts.traceability
    if status_filter:
        rows = [r for r in rows if r.status in status_filter]

    hidden = len(facts.traceability) - len(rows)
    if hidden:
        st.caption(
            f"Showing **{len(rows)}** of {len(facts.traceability)} rules — {hidden} hidden by "
            f"the status filter above. Clear the filter to see every rule."
        )

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

with tabs[3]:
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

with tabs[4]:
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

with tabs[4]:
    st.divider()
    st.subheader("Run history (this session)")
    history = st.session_state.get("run_history", [])
    if not history:
        st.info("No runs recorded yet.")
    else:
        # Underscore-prefixed keys carry the per-run payloads, not display data.
        visible = [{k: v for k, v in row.items() if not k.startswith("_")}
                   for row in history]
        st.dataframe(pd.DataFrame(visible), use_container_width=True, hide_index=True)
        st.caption(f"{len(history)} run(s) this session. Cleared when the app restarts.")

        st.markdown("#### Download a specific run")
        st.caption(
            "Each row below downloads **that run's own report** — the numbers captured "
            "when it executed, not the latest run's. Newest first."
        )
        for i, row in reversed(list(enumerate(history))):
            tag = f" · 🐞 {row['_bug']}" if row.get("_bug") else ""
            c1, c2, c3 = st.columns([5, 2, 2])
            c1.markdown(
                f"**Run {i + 1}** · {row['Scope']}{tag}<br>"
                f"<span style='font-size:.82rem;color:#6b7280;'>{row['Time']} · "
                f"{row['Pass rate']} pass · {row['Succeeded']} succeeded / "
                f"{row['Failed']} failed · {row['Divergences']} divergences</span>",
                unsafe_allow_html=True,
            )
            c2.download_button(
                "⬇ Report (CSV)", data=row["_csv"].encode("utf-8-sig"),
                file_name=row["_filename"], mime="text/csv",
                use_container_width=True, key=f"dl_csv_{i}",
            )
            trace = Path(row["_trace"])
            if trace.exists():
                c3.download_button(
                    "⬇ Trace (HTML)", data=trace.read_bytes(),
                    file_name=trace.name, mime="text/html",
                    use_container_width=True, key=f"dl_trace_{i}",
                )
            else:
                c3.caption("trace file gone")

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

with tabs[1]:
    st.divider()
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

with tabs[3]:
    st.divider()
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
        if st.session_state.get("cobol_source_url"):
            st.caption(f"→ Loaded from GitHub: {st.session_state['cobol_source_url']}")
        show_source(root / "data" / "src" / "legacy" / "INTCALC.cbl", "cobol")
    elif src_choice.startswith("📜"):
        show_source(root / "data" / "rules" / "validated_rules.yaml", "yaml")
    else:
        show_source(root / "generated" / "GeneratedIntcalc.java", "java")
        st.caption("This file is regenerated fresh on every run and is intentionally "
                   "**not** committed to git — it's disposable AI output, not a trusted "
                   "static artifact. The legacy COBOL and the rules file, by contrast, "
                   "are permanent and version-controlled.")

with tabs[4]:
    st.divider()
    st.subheader("Reports from this run")
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

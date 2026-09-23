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
from core.bulk_loader import generate_sample_bulk_csv, load_bulk_vectors_from_csv  # noqa: E402
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

# ai_platform/llm_client.py reads the API key from os.environ, but on
# Streamlit Cloud a value entered in the app's Secrets box lands in
# st.secrets, not necessarily in the process environment. Bridge it
# explicitly so "real" LLM mode works regardless of which one actually
# gets populated - this is a no-op wherever the env var is already set
# (e.g. local `export ANTHROPIC_API_KEY=...`).
if not os.environ.get("ANTHROPIC_API_KEY"):
    try:
        _secret_key = st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:
        _secret_key = None
    if _secret_key:
        os.environ["ANTHROPIC_API_KEY"] = _secret_key

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

    /* ------------------------------------------------------- sidebar theme
       A single deep-indigo gradient with one consistent teal accent,
       replacing the earlier dark-slate panel with mismatched per-card
       orange/pink/purple borders — one accent family reads calmer and
       more premium than a different color per section. */
    section[data-testid="stSidebar"],
    section[data-testid="stSidebar"] > div {
        background: linear-gradient(165deg, #0b1220 0%, #121b33 45%, #16213f 100%) !important;
        color: #e7ecf5 !important;
    }
    section[data-testid="stSidebar"] * {
        color: #e7ecf5 !important;
    }

    /* "## CodeVerus" wordmark at the top of the sidebar */
    section[data-testid="stSidebar"] h2 {
        font-weight: 800 !important;
        letter-spacing: .02em;
        background: linear-gradient(120deg, #5eead4 0%, #7dd3fc 100%);
        -webkit-background-clip: text;
        background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: .1rem !important;
    }
    section[data-testid="stSidebar"] [data-testid="stCaptionContainer"]:first-of-type,
    section[data-testid="stSidebar"] > div > div > div:nth-child(2) .stCaption {
        color: #8aa0c4 !important;
        letter-spacing: .02em;
    }

    /* Section headings ("#### Choose what to test", etc.) — small teal
       eyebrow label instead of plain bold white, so each card's purpose
       is scannable at a glance. */
    section[data-testid="stSidebar"] h4 {
        font-weight: 700 !important;
        font-size: .92rem !important;
        letter-spacing: .03em;
        text-transform: uppercase;
        color: #5eead4 !important;
        margin-bottom: .55rem !important;
        padding-bottom: .5rem !important;
        border-bottom: 1px solid #ffffff1c !important;
    }

    section[data-testid="stSidebar"] hr {
        border-color: #ffffff1c !important;
    }

    /* Card-grouped sections (st.container(border=True)) inside the sidebar —
       one soft glass-panel treatment, gently lit on hover so the active
       section reads clearly without needing a different color per card. */
    section[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] {
        background: linear-gradient(160deg, #ffffff10 0%, #ffffff06 100%) !important;
        border: 1px solid #ffffff1f !important;
        border-radius: 16px !important;
        padding: 1.1rem 1rem !important;
        margin-bottom: 1rem !important;
        box-shadow: 0 4px 18px rgba(0,0,0,.18) !important;
        transition: border-color .15s ease, box-shadow .15s ease;
    }
    section[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]:hover {
        border-color: #5eead450 !important;
        box-shadow: 0 6px 22px rgba(0,0,0,.24) !important;
    }

    /* The scope dropdown reads better as a light control against the dark panel */
    section[data-testid="stSidebar"] [data-baseweb="select"] > div {
        background: #ffffff !important;
        border-radius: 10px !important;
        border: 1px solid #ffffff3a !important;
    }
    section[data-testid="stSidebar"] [data-baseweb="select"] * {
        color: #0b1220 !important;
    }
    /* The open option list is rendered in a portal outside the sidebar */
    [data-baseweb="popover"] [role="listbox"],
    [data-baseweb="popover"] [role="listbox"] * {
        color: #0b1220 !important;
    }

    /* Text inputs / text areas / number inputs / file uploader inside the
       sidebar get the same light-control treatment as the dropdown, for
       the same readability reason. */
    section[data-testid="stSidebar"] input,
    section[data-testid="stSidebar"] textarea {
        background: #ffffff !important;
        color: #0b1220 !important;
        border-radius: 10px !important;
        border: 1px solid #ffffff3a !important;
    }
    section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
        background: #ffffff0d !important;
        border: 1px dashed #5eead460 !important;
        border-radius: 12px !important;
    }
    section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] * {
        color: #cdd9ee !important;
    }
    section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button {
        background: #ffffff14 !important;
        color: #e7ecf5 !important;
        border: 1px solid #ffffff3a !important;
    }

    section[data-testid="stSidebar"] .stCaption, section[data-testid="stSidebar"] small {
        color: #9db2d4 !important;
        line-height: 1.5;
    }
    section[data-testid="stSidebar"] code {
        background: #5eead422 !important; color: #99f6e4 !important;
    }

    /* Checkboxes/radios pick up the same teal accent as everything else. */
    section[data-testid="stSidebar"] [data-baseweb="checkbox"] svg,
    section[data-testid="stSidebar"] [data-baseweb="radio"] svg {
        fill: #5eead4 !important;
    }

    /* Buttons: one teal-to-blue gradient family for the sidebar, distinct
       from the primary red "Run pipeline" call-to-action, which keeps its
       own warmer accent so it still reads as the main action. */
    section[data-testid="stSidebar"] .stButton button {
        color: #ffffff !important;
        background: linear-gradient(120deg, #14b8a6 0%, #0ea5e9 100%) !important;
        border: none !important;
        border-radius: 10px !important;
        font-weight: 700 !important;
        box-shadow: 0 3px 10px rgba(14,165,233,.25) !important;
        transition: filter .15s ease, box-shadow .15s ease;
    }
    section[data-testid="stSidebar"] .stButton button:hover {
        filter: brightness(1.08);
        box-shadow: 0 5px 16px rgba(14,165,233,.35) !important;
    }
    section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] {
        background: linear-gradient(120deg, #e0503a 0%, #d6402e 100%) !important;
        box-shadow: 0 3px 10px rgba(214,64,46,.3) !important;
    }
    section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"]:hover {
        filter: brightness(1.08);
        box-shadow: 0 5px 16px rgba(214,64,46,.4) !important;
    }
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


# ------------------------------------------------------------ bulk CSV report
def build_bulk_csv_report(bulk, source_label: str) -> str:
    """Same labelled-sections shape as build_csv_report(), but sized for a
    batch of hundreds/thousands of records: a summary block, a per-field
    mismatch breakdown, the rule-level rollup, and every individual
    divergence with its (deduplicated) diagnosis — not a full evidence
    pack, which assumes a hand-reviewable vector count."""
    diag_by_vector = {d.vector_id: d for d in bulk.diagnoses}
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")

    w.writerow(["CodeVerus - bulk record validation report"])
    w.writerow(["Generated", _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    w.writerow(["Batch", source_label])
    w.writerow(["Generated code validated against", bulk.source.path])
    w.writerow(["Elapsed", f"{bulk.elapsed_ms / 1000:.1f}s"])
    w.writerow([])

    w.writerow(["SUMMARY"])
    w.writerow(["Metric", "Count", "Percent"])
    w.writerow(["Records validated", bulk.total_records, ""])
    w.writerow(["Matched the legacy oracle exactly", bulk.matched_records, f"{bulk.pass_rate:.1f}%"])
    w.writerow(["Diverged on at least one field", bulk.mismatched_records,
                f"{100 - bulk.pass_rate:.1f}%" if bulk.total_records else ""])
    w.writerow(["Field-level divergence records", len(bulk.divergences), ""])
    w.writerow(["Distinct failure patterns diagnosed",
                len({(d.field, tuple(d.rule_ids)) for d in bulk.divergences}), ""])
    w.writerow([])

    w.writerow(["PER-FIELD MISMATCH COUNTS"])
    w.writerow(["Field", "Mismatches"])
    for field_name, count in bulk.per_field_mismatch_counts().items():
        w.writerow([field_name, count])
    w.writerow([])

    w.writerow(["RULE-LEVEL ROLLUP"])
    w.writerow(["Rule ID", "Status", "Records citing this rule"])
    for row in bulk.matrix:
        w.writerow([row.rule_id, row.status, len(row.tests)])
    w.writerow([])

    w.writerow(["EVERY DIVERGENCE (record, field, expected vs actual, diagnosis)"])
    w.writerow(["Record ID", "Field", "Legacy (expected)", "Generated (actual)",
                "Rule IDs", "Cause", "Explanation"])
    for d in bulk.divergences:
        diag = diag_by_vector.get(d.vector_id)
        w.writerow([
            d.vector_id, d.field, d.expected, d.actual, "; ".join(d.rule_ids),
            diag.cause if diag else "", " ".join((diag.explanation if diag else "").split()),
        ])

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

    with st.container(border=True):
        st.markdown("#### Bulk record validation")
        if prior_result is None:
            st.caption(
                "Run the pipeline once above first — bulk validation checks a large "
                "batch of records against the code that run already generated, it "
                "doesn't generate anything new."
            )
            bulk_run_clicked = False
            bulk_file = None
            bulk_use_sample = False
        else:
            st.caption(
                "Upload a CSV of many input records (e.g. a month of account "
                "activity) and validate every one against the already-generated "
                "implementation — same oracle-vs-generated-code check as a single "
                "vector, just run at volume, with AI diagnosis reused across "
                "records that fail for the same reason instead of re-explaining "
                "each one."
            )
            bulk_file = st.file_uploader(
                "Bulk records CSV", type=["csv"], key="bulk_csv_upload",
                label_visibility="collapsed",
            )
            bulk_use_sample = st.checkbox(
                "No file handy — generate a synthetic sample batch instead",
                key="bulk_use_sample",
            )
            bulk_n = 500
            if bulk_use_sample:
                bulk_n = st.number_input(
                    "Sample size", min_value=10, max_value=20000, value=500, step=50,
                    key="bulk_sample_n",
                )
            bulk_run_clicked = st.button(
                "📦  Run bulk validation", use_container_width=True,
                disabled=not (bulk_file is not None or bulk_use_sample),
            )


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

if bulk_run_clicked:
    prior = st.session_state.get("result")
    if prior is None:
        st.warning("Run the pipeline once before bulk-validating records against it.")
    else:
        try:
            if bulk_use_sample:
                bulk_csv_path = generate_sample_bulk_csv(
                    Path("runs") / "bulk_uploads" / "sample_batch.csv",
                    get_pipeline().sig, n=int(bulk_n),
                )
                bulk_label = f"synthetic sample batch ({int(bulk_n)} records)"
            else:
                Path("runs/bulk_uploads").mkdir(parents=True, exist_ok=True)
                bulk_csv_path = Path("runs/bulk_uploads") / bulk_file.name
                bulk_csv_path.write_bytes(bulk_file.getvalue())
                bulk_label = bulk_file.name

            bulk_vectors = load_bulk_vectors_from_csv(bulk_csv_path, get_pipeline().sig)
            with st.spinner(f"Validating {len(bulk_vectors)} records against the generated code..."):
                bulk_result = get_pipeline().run_bulk(
                    bulk_vectors, source=prior.source,
                    run_id=f"ui-bulk-{_dt.datetime.now():%H%M%S}",
                )
            st.session_state["bulk_result"] = bulk_result
            st.session_state["bulk_label"] = bulk_label
            st.session_state["bulk_csv_report"] = build_bulk_csv_report(bulk_result, bulk_label)
            st.session_state["bulk_report_filename"] = (
                f"codeverus_bulk_report_{_dt.datetime.now():%Y%m%d_%H%M%S}.csv"
            )
            st.rerun()
        except ValueError as exc:
            st.error(f"Couldn't read that bulk file: {exc}")

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
def score_panel(title: str, headline: str, headline_sub: str, accent: str,
                rows: list[tuple[str, str, int, float]]) -> str:
    """rows: (color, label, count, pct) — rendered as a stacked bar + legend."""
    bar = "".join(
        f'<div class="score-seg" title="{label}: {pct:.1f}%" '
        f'style="width:{pct:.3f}%; background:{color};"></div>'
        for color, label, count, pct in rows if pct > 0
    )
    legend = "".join(
        f'<div class="score-row">'
        f'<span class="score-sw" style="background:{color};"></span>'
        f'<span class="score-pct">{pct:.1f}%</span>'
        f'<span class="score-lbl">{label}</span>'
        f'<span class="score-cnt">{count}</span></div>'
        for color, label, count, pct in rows
    )
    return f"""
    <div class="score-panel" style="--accent:{accent};">
        <div class="score-title">{title}</div>
        <div class="score-headline">{headline}</div>
        <div class="score-sub">{headline_sub}</div>
        <div class="score-bar">{bar}</div>
        <div class="score-rows">{legend}</div>
    </div>
    """


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

p1, p2 = st.columns(2)
p1.markdown(score_panel(
    "Rule validation · success rate",
    f"{_pct(n_ok, n_rules):.1f}%",
    f"{n_ok} of {n_rules} rules validated flawless",
    c_ok,
    [(c_ok, "Succeeded — validated flawless", n_ok, _pct(n_ok, n_rules)),
     (c_bad, "Failed — flaw found", n_bad, _pct(n_bad, n_rules)),
     (c_na, "Not testable — uncoverable / untested", n_na, _pct(n_na, n_rules))],
), unsafe_allow_html=True)

p2.markdown(score_panel(
    "Test execution · match rate",
    f"{_pct(n_vec_ok, n_vec):.1f}%",
    f"{n_vec_ok} of {n_vec} vectors matched the COBOL oracle exactly",
    ACCENT_NEUTRAL,
    [(c_ok, "Succeeded — output identical to oracle", n_vec_ok, _pct(n_vec_ok, n_vec)),
     (c_bad, "Diverged — at least one field differs", n_vec_bad, _pct(n_vec_bad, n_vec))],
), unsafe_allow_html=True)

st.write("")

# A scope narrower than the whole rule file must say so, so a 100% score is
# never read as "all 24 rules pass".
if st.session_state.get("scope_key") != "Full run" and n_rules < 24:
    st.info(
        f"**Scope: {st.session_state.get('scope_key')}** — these percentages cover the "
        f"{n_rules} rules in this scope, not all 24. Choose **Full run** in the sidebar "
        f"for the complete picture."
    )

# One honest headline: of the rules that CAN be judged, how many passed.
if n_testable:
    st.markdown(
        f"#### ✅ {_pct(n_ok, n_testable):.1f}% pass rate on testable rules "
        f"<span style='font-size:.8rem;font-weight:500;color:#6b7280;'>"
        f"({n_ok} passed / {n_bad} failed, out of the {n_testable} rules with both a test "
        f"and a code path — the other {n_na} cannot be judged from this module's output)"
        f"</span>",
        unsafe_allow_html=True,
    )

with st.expander(f"Breakdown of the {n_bad} failures and {n_na} not-testable rules"):
    status_counts = pd.Series([row.status for row in facts.traceability]).value_counts()
    brk = [{"Status": f"{STATUS_META[s]['icon']} {STATUS_META[s]['label']}",
            "Rules": int(status_counts.get(s, 0)),
            "% of all rules": f"{_pct(int(status_counts.get(s, 0)), n_rules):.1f}%",
            "Rules affected": ", ".join(r.rule_id for r in facts.traceability if r.status == s) or "—"}
           for s in STATUS_ORDER if int(status_counts.get(s, 0)) > 0]
    st.dataframe(pd.DataFrame(brk), use_container_width=True, hide_index=True)
    st.caption(
        f"{facts.total_divergences} field-level divergence records across "
        f"{n_vec_bad} diverging vectors — one record per (vector, field) pair, so a vector "
        f"that disagrees on two fields counts twice."
    )

st.write("")

tabs = st.tabs(["✅ Rule results", "🔬 Divergences & findings", "📄 Evidence pack",
                "🧾 Data & source", "🕘 History & downloads", "📦 Bulk validation"])

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

with tabs[5]:
    st.subheader("Bulk record validation")
    st.caption(
        "Validates a large batch of records — e.g. a month of account activity — "
        "against the implementation this session already generated. Divergences "
        "are grouped by failure pattern before diagnosis, so a batch where "
        "thousands of records fail for the same reason still costs one AI "
        "explanation, not thousands."
    )
    bulk_result = st.session_state.get("bulk_result")
    if bulk_result is None:
        st.info(
            "👈 Upload a CSV of input records (or generate a synthetic sample "
            "batch) in the sidebar's **Bulk record validation** section, then "
            "click **Run bulk validation**."
        )
    else:
        bulk_label = st.session_state.get("bulk_label", "")
        st.caption(f"Batch: **{bulk_label}** · validated against `{bulk_result.source.path}` "
                   f"in {bulk_result.elapsed_ms / 1000:.1f}s")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Records validated", f"{bulk_result.total_records:,}")
        m2.metric("Matched the oracle", f"{bulk_result.matched_records:,}",
                   f"{bulk_result.pass_rate:.1f}%")
        m3.metric("Diverged", f"{bulk_result.mismatched_records:,}")
        m4.metric("Field-level divergences", f"{len(bulk_result.divergences):,}")

        field_counts = bulk_result.per_field_mismatch_counts()
        if field_counts:
            st.markdown("#### Mismatches by field")
            st.dataframe(
                pd.DataFrame(
                    [{"Field": k, "Mismatches": v} for k, v in field_counts.items()]
                ),
                use_container_width=True, hide_index=True,
            )
        else:
            st.success("Every record in this batch matched the legacy oracle exactly.")

        st.markdown("#### Rule-level rollup for this batch")
        st.dataframe(
            pd.DataFrame([
                {"Rule": row.rule_id, "Status": row.status,
                 "Records citing it": len(row.tests)}
                for row in bulk_result.matrix
            ]),
            use_container_width=True, hide_index=True,
        )

        if bulk_result.untraceable_findings:
            st.markdown("#### Untraceable-behaviour findings in this batch")
            for f in bulk_result.untraceable_findings:
                st.warning(f"**{f.id}**: {f.description} "
                           f"({len(f.triggering_vectors)} record(s))")

        st.markdown("#### Sample diverged records")
        st.caption(
            "Each distinct failure pattern was diagnosed once by DivergenceAI and "
            "the same explanation applied to every record sharing it — shown below "
            "per record so you can see exactly which ones."
        )
        diag_by_vector = {d.vector_id: d for d in bulk_result.diagnoses}
        sample_rows = []
        for d in bulk_result.divergences[:200]:
            diag = diag_by_vector.get(d.vector_id)
            sample_rows.append({
                "Record ID": d.vector_id, "Field": d.field,
                "Legacy (expected)": d.expected, "Generated (actual)": d.actual,
                "Cause": diag.cause if diag else "—",
            })
        if sample_rows:
            st.dataframe(pd.DataFrame(sample_rows), use_container_width=True, hide_index=True)
            if len(bulk_result.divergences) > 200:
                st.caption(f"... and {len(bulk_result.divergences) - 200} more. "
                           f"Download the full report below for every record.")

        st.markdown("#### Download")
        bulk_csv = st.session_state.get("bulk_csv_report")
        if bulk_csv:
            st.download_button(
                "⬇ Full bulk report (CSV)", data=bulk_csv.encode("utf-8-sig"),
                file_name=st.session_state.get("bulk_report_filename", "bulk_report.csv"),
                mime="text/csv", use_container_width=True,
            )
        trace_path = Path(bulk_result.trace_path)
        if trace_path.exists():
            st.download_button(
                "⬇ Run trace (HTML)", data=trace_path.read_bytes(),
                file_name=trace_path.name, mime="text/html",
                use_container_width=True, key="bulk_trace_dl",
            )

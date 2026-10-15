"""System status & setup helpers (DB, company list, Gemini, RAGFlow)."""
from __future__ import annotations

import importlib.util
import tempfile

import streamlit as st

from core import db
from core import repository as repo
from core.company_list import NSE_EQUITY_URL, load_companies
from core.config import get_settings
from rag.ragflow_client import RagFlowClient
from rag.sync import sync_company
from ui import components as C


def render(embedded: bool = False) -> None:
    s = get_settings()
    if not embedded:
        C.page_header("System status", "Check connections, load the NSE company list and manage the RAGFlow "
                      "knowledge base.")

    C.section("Connections", "Live status of every service the app depends on")
    c1, c2, c3 = st.columns(3, gap="medium")
    with c1:
        ok = db.ping()
        st.metric("Supabase database", "Connected" if ok else "Not connected")
        if ok:
            st.caption(f"{repo.count_companies():,} companies in the master list")
    with c2:
        st.metric("Gemini", "Configured" if s.llm_enabled else "Missing key")
        from analysis import llm as _llm

        st.caption(f"Model: {_llm.model_name()}" + (f" (auto-selected; {s.gemini_model} is not available)"
                                                    if _llm.model_name() != s.gemini_model else ""))
    with c3:
        if s.rag_configured:
            alive = RagFlowClient().ping()
            st.metric("RAGFlow", "Online" if alive else "Unreachable")
            st.caption(s.ragflow_base_url)
        else:
            st.metric("RAGFlow", "Disabled")
            st.caption("Chatbot uses Gemini over stored data")

    C.section("Analysis add-ons", "Used only while an analysis report is generated; the Screener scrape is separate")
    d1, d2 = st.columns(2, gap="medium")
    with d1:
        def _has(mod: str) -> bool:
            try:
                return importlib.util.find_spec(mod) is not None
            except (ValueError, ImportError):
                return False

        missing = [m for m in ("sklearn", "scipy") if not _has(m)]
        st.metric("Projection libraries", "Ready" if not missing else "Missing")
        st.caption("scikit-learn and SciPy" if not missing else
                   f"Not installed: {', '.join(missing)} — run pip install -r requirements.txt")
        from analysis import timesfm_model

        tf = timesfm_model.status()
        if not tf["enabled"]:
            st.caption("TimesFM (Google AI forecasting model): off. To use it: pip install \"timesfm[torch]\" and set "
                       "TIMESFM_ENABLED=true in .env")
        elif tf["loaded"]:
            st.caption(f"TimesFM: loaded ({tf['checkpoint']}, {tf['api']}) — used as a 4th projection model")
        else:
            st.caption(f"TimesFM: enabled but not loaded — {tf['error']}")
    with d2:
        if not s.external_enabled:
            st.metric("Other websites", "Switched off")
            st.caption("EXTERNAL_SOURCES_ENABLED=false — reports use Screener only")
        else:
            try:
                has_yf = importlib.util.find_spec("yfinance") is not None
            except (ValueError, ImportError):
                has_yf = False
            st.metric("Other websites", "Connected" if has_yf and s.llm_enabled else "Partly connected")
            st.caption("Yahoo Finance: " + ("yfinance installed" if has_yf else "yfinance not installed")
                       + " · AI search of " + ", ".join(d for d in s.external_sites if "yahoo" not in d)
                       + (": ready" if s.llm_enabled else ": needs the Gemini key"))

    C.section("Company master list (NSE)", f"Official NSE equity list — {NSE_EQUITY_URL}", color="green")
    a, b = st.columns(2, gap="medium")
    with a:
        with st.container(border=True):
            C.subheading("Download from NSE")
            sme = st.checkbox("Include NSE SME (Emerge) companies")
            if st.button("Download & load NSE list", type="primary", use_container_width=True):
                with st.spinner("Downloading from NSE…"):
                    try:
                        n = load_companies(include_sme=sme)
                        st.success(f"Loaded/updated {n:,} companies.")
                        st.cache_data.clear()
                    except Exception as e:  # noqa: BLE001
                        st.error(f"Download failed ({e}). Download the CSV in your browser and upload it →")
    with b:
        with st.container(border=True):
            C.subheading("Upload CSV", color="green")
            up = st.file_uploader("EQUITY_L.csv", type=["csv"], label_visibility="collapsed")
            if up is not None and st.button("Load uploaded CSV", use_container_width=True):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as f:
                    f.write(up.getvalue())
                try:
                    n = load_companies(f.name)
                    st.success(f"Loaded/updated {n:,} companies.")
                    st.cache_data.clear()
                except Exception as e:  # noqa: BLE001
                    st.error(str(e))

    C.section("RAGFlow knowledge base", "Per-company dataset and chat assistant used by the chatbot")
    with st.container(border=True):
        company = st.session_state.get("company")
        if not company:
            st.caption("Open a company on the Stocks tab to see its sync state.")
        else:
            state = repo.get_rag_state(company["id"]) or {}
            x, y = st.columns([3, 1], vertical_alignment="center")
            with x:
                st.markdown(f"**{company['name']}** — status: `{state.get('status', 'not synced')}` "
                            f"{state.get('message') or ''}")
                if state.get("last_synced_at"):
                    st.caption(f"Last synced {state['last_synced_at']} · dataset {state.get('dataset_id')} · "
                               f"chat {state.get('chat_id')}")
            with y:
                go = st.button("Sync this company now", disabled=not s.rag_configured, use_container_width=True)
            if go:
                with st.spinner("Uploading and parsing documents in RAGFlow (can take a minute)…"):
                    res = sync_company(company["id"])
                (st.success if res.get("status") in ("ready", "parsing") else st.error)(str(res))
        pending = repo.companies_needing_rag_sync() if db.ping() else []
        st.caption(f"{len(pending)} companies have newer data than RAGFlow. "
                   "Run `python -m scripts.rag_sync_all --loop 15` to keep everything synced continuously.")

"""Central configuration loaded from environment / .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


# Extra websites used ONLY while building the analysis report (never during the Screener scrape)
DEFAULT_EXTERNAL_SITES = "finance.yahoo.com,valueresearchonline.com,investing.com,macrotrends.net"


def _get_secret(name: str, default: str = "") -> str:
    """Read from env first, then from Streamlit secrets (for Streamlit Cloud)."""
    val = os.getenv(name)
    if val:
        return val.strip()
    try:  # streamlit secrets are optional
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name]).strip()
    except Exception:
        pass
    return default


def _clean_supabase_url(url: str) -> str:
    """Accept common copy-paste mistakes: trailing '/', '/rest/v1', '/auth/v1'."""
    url = url.strip().strip('"').strip("'").rstrip("/")
    for suffix in ("/rest/v1", "/auth/v1", "/storage/v1"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url.rstrip("/")


def _int(v: str, default: int) -> int:
    try:
        return max(0, int(str(v).strip()))
    except (TypeError, ValueError):
        return default


def _bool(v: str, default: bool = False) -> bool:
    if v == "":
        return default
    return v.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_anon_key: str
    database_url: str
    gemini_api_key: str
    gemini_model: str
    ragflow_base_url: str
    ragflow_api_key: str
    ragflow_enabled: bool
    scraper_delay: float
    screener_sessionid: str
    gemini_fallback_model: str = ""
    external_enabled: bool = True
    timesfm_enabled: bool = True
    timesfm_checkpoint: str = "google/timesfm-2.5-200m-pytorch"
    timesfm_device: str = "cpu"
    external_sites: tuple = ()
    external_strict: bool = True
    news_per_source: int = 15
    report_news_per_source: int = 5
    pdf_news_max: int = 70

    @property
    def llm_enabled(self) -> bool:
        return bool(self.gemini_api_key) and not self.gemini_api_key.startswith("your-")

    @property
    def rag_configured(self) -> bool:
        return self.ragflow_enabled and bool(self.ragflow_api_key) and "xxxx" not in self.ragflow_api_key


def get_settings() -> Settings:
    return Settings(
        supabase_url=_clean_supabase_url(_get_secret("SUPABASE_URL")),
        supabase_anon_key=_get_secret("SUPABASE_ANON_KEY"),
        database_url=_get_secret("DATABASE_URL"),
        gemini_api_key=_get_secret("GEMINI_API_KEY"),
        gemini_model=_get_secret("GEMINI_MODEL", "gemini-3.1-flash-lite"),
        gemini_fallback_model=_get_secret("GEMINI_FALLBACK_MODEL", ""),
        timesfm_enabled=_bool(_get_secret("TIMESFM_ENABLED", "true"), True),
        timesfm_checkpoint=_get_secret("TIMESFM_CHECKPOINT", "google/timesfm-2.5-200m-pytorch"),
        timesfm_device=_get_secret("TIMESFM_DEVICE", "cpu"),
        ragflow_base_url=_get_secret("RAGFLOW_BASE_URL", "http://localhost:9380").rstrip("/"),
        ragflow_api_key=_get_secret("RAGFLOW_API_KEY"),
        ragflow_enabled=_bool(_get_secret("RAGFLOW_ENABLED", "true"), True),
        scraper_delay=float(_get_secret("SCRAPER_DELAY_SECONDS", "1.0") or 1.0),
        screener_sessionid=_get_secret("SCREENER_SESSIONID"),
        external_enabled=_bool(_get_secret("EXTERNAL_SOURCES_ENABLED", "true"), True),
        external_sites=tuple(d.strip().lower() for d in _get_secret("EXTERNAL_SITES", DEFAULT_EXTERNAL_SITES).split(",")
                             if d.strip()),
        external_strict=_bool(_get_secret("EXTERNAL_STRICT", "true"), True),
        news_per_source=_int(_get_secret("NEWS_PER_SOURCE", "15"), 15),
        report_news_per_source=_int(_get_secret("REPORT_NEWS_PER_SOURCE", "5"), 5),
        pdf_news_max=_int(_get_secret("PDF_NEWS_MAX", "70"), 70),
    )


APP_NAME = "Stock Insight Studio"
PARSER_VERSION = "screener-html-v1"

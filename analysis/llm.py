"""Google Gemini wrapper (google-genai SDK)."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from core.config import get_settings

log = logging.getLogger(__name__)
_client = None


class LLMUnavailable(RuntimeError):
    pass


def _get_client():
    global _client
    s = get_settings()
    if not s.llm_enabled:
        raise LLMUnavailable("GEMINI_API_KEY is not configured.")
    if _client is None:
        from google import genai

        _client = genai.Client(api_key=s.gemini_api_key)
    return _client


def model_name() -> str:
    return get_settings().gemini_model


def generate_text(prompt: str, system: str | None = None, temperature: float = 0.3,
                  max_tokens: int = 4096) -> str:
    from google.genai import types

    client = _get_client()
    resp = client.models.generate_content(
        model=model_name(),
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system, temperature=temperature, max_output_tokens=max_tokens),
    )
    return (resp.text or "").strip()


def generate_json(prompt: str, schema: Any, system: str | None = None, temperature: float = 0.3,
                  max_tokens: int = 16000) -> dict:
    """Ask Gemini for JSON matching `schema` (a pydantic model class)."""
    from google.genai import types

    client = _get_client()
    resp = client.models.generate_content(
        model=model_name(),
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
            response_schema=schema,
        ),
    )
    parsed = getattr(resp, "parsed", None)
    if parsed is not None:
        return parsed.model_dump() if hasattr(parsed, "model_dump") else dict(parsed)
    return _extract_json(resp.text or "")


def generate_grounded(prompt: str, system: str | None = None, temperature: float = 0.1,
                      max_tokens: int = 8192) -> dict:
    """Ask Gemini with Google Search grounding switched on.

    Returns {"text": str, "sources": [{"title", "url"}], "queries": [str]}.  Search grounding cannot be
    combined with a response schema, so callers ask for JSON in the prompt and parse the text.
    """
    from google.genai import types

    client = _get_client()
    resp = client.models.generate_content(
        model=model_name(),
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system, temperature=temperature, max_output_tokens=max_tokens,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        ),
    )
    sources, queries = [], []
    try:
        gm = resp.candidates[0].grounding_metadata
        for ch in (getattr(gm, "grounding_chunks", None) or []):
            web = getattr(ch, "web", None)
            if web is not None:
                sources.append({"title": getattr(web, "title", "") or "", "url": getattr(web, "uri", "") or ""})
        queries = list(getattr(gm, "web_search_queries", None) or [])
    except Exception:  # noqa: BLE001 - grounding metadata is optional
        pass
    return {"text": (resp.text or "").strip(), "sources": sources, "queries": queries}


def extract_json(text: str) -> dict:
    """Public wrapper: parse a JSON object out of model text (handles ```json fences)."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.S)
    return _extract_json(text)


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def is_available() -> bool:
    return get_settings().llm_enabled


def safe_generate_text(prompt: str, system: str | None = None) -> Optional[str]:
    try:
        return generate_text(prompt, system)
    except Exception as e:  # noqa: BLE001
        log.warning("Gemini call failed: %s", e)
        return None

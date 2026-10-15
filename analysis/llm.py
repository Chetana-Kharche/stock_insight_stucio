"""Google Gemini wrapper (google-genai SDK)."""
from __future__ import annotations

import json
import logging
import re
import time
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


_last_model: Optional[str] = None
RETRYABLE = ("503", "429", "500", "unavailable", "overloaded", "high demand", "resource_exhausted",
             "deadline", "timed out", "internal")


def model_name() -> str:
    """The model that answered the last call (the main model, or the fallback if it was needed)."""
    return _last_model or _auto_model or get_settings().gemini_model


# ------------------------------------------------------------------ choosing a model that exists
# Google retires model names over time (e.g. gemini-2.5-flash returns 404 "no longer available to new users").
# When the configured model is missing, the app asks the API which models this key can use and picks the
# newest stable Flash model, so the report keeps working without editing .env.
GONE = ("404", "not_found", "not found", "no longer available", "is not supported", "deprecated")
_auto_model: Optional[str] = None
_SKIP = ("preview", "exp", "image", "tts", "audio", "live", "embedding", "thinking", "native", "robotics",
         "computer", "learnlm", "gemma", "aqa", "veo", "imagen")


def _version(name: str) -> tuple:
    m = re.search(r"gemini-(\d+)(?:\.(\d+))?", name)
    return (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 0)


def pick_available_model(client, exclude: tuple = ()) -> Optional[str]:
    """Newest stable 'flash' (preferred) or 'flash-lite' model that supports generateContent."""
    found = []
    try:
        for m in client.models.list():
            name = (getattr(m, "name", "") or "").split("/")[-1]
            actions = [a.lower() for a in (getattr(m, "supported_actions", None) or [])]
            if not name.startswith("gemini-") or "flash" not in name or name in exclude:
                continue
            if any(k in name for k in _SKIP):
                continue
            if actions and not any("generatecontent" in a for a in actions):
                continue
            found.append(name)
    except Exception as e:  # noqa: BLE001
        log.warning("Could not list Gemini models: %s", e)
        return None
    if not found:
        return None
    found.sort(key=lambda n: (_version(n), "lite" not in n, not n.endswith("latest")), reverse=True)
    return found[0]


def _generate(client, contents, config):
    """generate_content with retries when Gemini is busy (503/429), an optional fallback model, and an automatic
    switch to an available model when the configured one has been retired (404)."""
    global _last_model, _auto_model
    s = get_settings()
    models = [_auto_model or s.gemini_model] + ([s.gemini_fallback_model] if s.gemini_fallback_model else [])
    tried: list[str] = []
    last_err: Optional[Exception] = None
    while models:
        model = models.pop(0)
        if not model or model in tried:
            continue
        tried.append(model)
        for attempt, wait in enumerate((0, 3, 8)):
            if wait:
                time.sleep(wait)
            try:
                resp = client.models.generate_content(model=model, contents=contents, config=config)
                _last_model = model
                return resp
            except Exception as e:  # noqa: BLE001
                last_err = e
                low = str(e).lower()
                if any(k in low for k in GONE):
                    alt = pick_available_model(client, exclude=tuple(tried))
                    if alt:
                        log.warning("Gemini model %s is not available; switching to %s", model, alt)
                        _auto_model = alt
                        models.insert(0, alt)
                    break
                if not any(k in low for k in RETRYABLE):
                    raise
                log.warning("Gemini %s busy (attempt %d): %s", model, attempt + 1, str(e)[:120])
    raise last_err  # type: ignore[misc]


def generate_text(prompt: str, system: str | None = None, temperature: float = 0.3,
                  max_tokens: int = 4096) -> str:
    from google.genai import types

    client = _get_client()
    resp = _generate(client, prompt, types.GenerateContentConfig(
            system_instruction=system, temperature=temperature, max_output_tokens=max_tokens),
    )
    return (resp.text or "").strip()


def generate_json(prompt: str, schema: Any, system: str | None = None, temperature: float = 0.3,
                  max_tokens: int = 16000) -> dict:
    """Ask Gemini for JSON matching `schema` (a pydantic model class)."""
    from google.genai import types

    client = _get_client()
    resp = _generate(client, prompt, types.GenerateContentConfig(
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
    resp = _generate(client, prompt, types.GenerateContentConfig(
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

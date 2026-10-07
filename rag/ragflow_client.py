"""Minimal client for RAGFlow's official HTTP API (v1).

Docs: https://ragflow.io/docs/dev/http_api_reference
We call the REST API directly (instead of the python SDK) because it is stable across
RAGFlow releases and gives clear error messages.
"""
from __future__ import annotations

import re
from typing import Any, Optional

import requests

from core.config import get_settings


class RagFlowError(RuntimeError):
    pass


class RagFlowClient:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, timeout: int = 60):
        s = get_settings()
        self.base = (base_url or s.ragflow_base_url).rstrip("/") + "/api/v1"
        self.key = api_key or s.ragflow_api_key
        self.timeout = timeout

    # ------------------------------------------------------------------ http
    def _req(self, method: str, path: str, *, json: Any = None, params: dict | None = None,
             files: Any = None, timeout: int | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self.key}"}
        try:
            r = requests.request(method, self.base + path, headers=headers, json=json, params=params,
                                 files=files, timeout=timeout or self.timeout)
        except requests.RequestException as e:
            raise RagFlowError(f"Cannot reach RAGFlow at {self.base}: {e}") from e
        try:
            body = r.json()
        except ValueError as e:
            raise RagFlowError(f"RAGFlow returned HTTP {r.status_code}: {r.text[:300]}") from e
        if body.get("code", 0) != 0:
            raise RagFlowError(f"RAGFlow error {body.get('code')}: {body.get('message')}")
        return body.get("data")

    def ping(self) -> bool:
        try:
            self._req("GET", "/datasets", params={"page": 1, "page_size": 1}, timeout=8)
            return True
        except RagFlowError:
            return False

    # ------------------------------------------------------------------ datasets
    def find_dataset(self, name: str) -> Optional[dict]:
        try:
            data = self._req("GET", "/datasets", params={"name": name})
        except RagFlowError as e:
            if _is_missing(e):
                return None
            raise
        for d in data or []:
            if d.get("name") == name:
                return d
        return None

    def create_dataset(self, name: str, description: str = "") -> dict:
        return self._req("POST", "/datasets", json={
            "name": name, "description": description[:600], "chunk_method": "naive",
            "parser_config": {"chunk_token_num": 384, "html4excel": False},
        })

    def get_or_create_dataset(self, name: str, description: str = "") -> dict:
        return self.find_dataset(name) or self.create_dataset(name, description)

    # ------------------------------------------------------------------ documents
    def upload_document(self, dataset_id: str, filename: str, content: str) -> dict:
        files = [("file", (filename, content.encode("utf-8"), "text/markdown"))]
        data = self._req("POST", f"/datasets/{dataset_id}/documents", files=files, timeout=120)
        return data[0] if isinstance(data, list) else data

    def delete_documents(self, dataset_id: str, ids: list[str]) -> None:
        if ids:
            try:
                self._req("DELETE", f"/datasets/{dataset_id}/documents", json={"ids": ids})
            except RagFlowError:
                pass  # already gone

    def list_documents(self, dataset_id: str, page_size: int = 100) -> list[dict]:
        data = self._req("GET", f"/datasets/{dataset_id}/documents", params={"page": 1, "page_size": page_size})
        return (data or {}).get("docs", []) if isinstance(data, dict) else (data or [])

    def parse_documents(self, dataset_id: str, ids: list[str]) -> None:
        self._req("POST", f"/datasets/{dataset_id}/chunks", json={"document_ids": ids})

    # ------------------------------------------------------------------ chats
    def find_chat(self, name: str) -> Optional[dict]:
        try:
            data = self._req("GET", "/chats", params={"name": name})
        except RagFlowError as e:
            if _is_missing(e):
                return None
            raise
        for c in data or []:
            if c.get("name") == name:
                return c
        return None

    def create_chat(self, name: str, dataset_ids: list[str], company_name: str) -> dict:
        system = (
            f"You are a financial research assistant for {company_name}. Answer ONLY from the knowledge base "
            "below, which contains data scraped from Screener.in, exchange announcements, news headlines and an "
            "AI-assisted analysis report. Always state the period (quarter/year) and unit (₹ crore, %) of numbers. "
            "If the answer is not in the knowledge base, say you don't have that data. Do not give buy/sell advice.\n"
            "Here is the knowledge base:\n{knowledge}\nThe above is the knowledge base."
        )
        return self._req("POST", "/chats", json={
            "name": name,
            "dataset_ids": dataset_ids,
            "description": f"Q&A over stored data for {company_name}",
            "prompt": {
                "prompt": system,
                "similarity_threshold": 0.1,
                "keywords_similarity_weight": 0.5,
                "top_n": 12,
                "show_quote": False,
                "empty_response": "",
                "opener": f"Ask me anything about {company_name}.",
                "variables": [{"key": "knowledge", "optional": True}],
            },
        })

    def update_chat_datasets(self, chat_id: str, dataset_ids: list[str]) -> None:
        self._req("PUT", f"/chats/{chat_id}", json={"dataset_ids": dataset_ids})

    def create_session(self, chat_id: str, name: str) -> str:
        data = self._req("POST", f"/chats/{chat_id}/sessions", json={"name": name[:100]})
        return data["id"]

    def ask(self, chat_id: str, question: str, session_id: Optional[str] = None) -> tuple[str, Optional[str], list]:
        payload = {"question": question, "stream": False}
        if session_id:
            payload["session_id"] = session_id
        data = self._req("POST", f"/chats/{chat_id}/completions", json=payload, timeout=180)
        answer = clean_answer((data or {}).get("answer", ""))
        refs = ((data or {}).get("reference") or {}).get("chunks", []) if isinstance(data, dict) else []
        return answer, (data or {}).get("session_id", session_id), refs


def _is_missing(e: Exception) -> bool:
    msg = str(e).lower()
    return any(k in msg for k in ("exist", "own the", "permission", "not found"))


def clean_answer(text: str) -> str:
    text = re.sub(r"\s*##\d+\$\$", "", text or "")
    text = re.sub(r"\s*\[ID:\d+\]", "", text)
    return text.strip()

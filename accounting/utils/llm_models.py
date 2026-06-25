"""
以 REST 取得 OpenAI / Anthropic 可用模型 id 清單（不依賴官方 SDK）。
"""
from __future__ import annotations

from typing import List

import requests


def _openai_is_chat_like(model_id: str) -> bool:
    mid = (model_id or "").strip().lower()
    if not mid:
        return False
    skip = (
        "embedding",
        "whisper",
        "moderation",
        "tts",
        "dall-e",
        "davinci",
        "babbage",
        "ada",
        "curie",
        "text-search",
        "code-search",
        "audio",
        "realtime",
        "transcribe",
        "speech",
    )
    if any(x in mid for x in skip):
        return False
    if mid.startswith("gpt-"):
        return True
    if mid.startswith(("o1", "o3", "o4")):
        return True
    if mid.startswith("chatgpt-"):
        return True
    if mid.startswith("ft:gpt-"):
        return True
    return False


def fetch_openai_model_ids(api_key: str, timeout: float = 45.0) -> List[str]:
    key = (api_key or "").strip()
    if not key:
        return []
    r = requests.get(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {key}"},
        timeout=timeout,
    )
    r.raise_for_status()
    payload = r.json()
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    out: List[str] = []
    for m in rows:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id") or "").strip()
        if mid and _openai_is_chat_like(mid):
            out.append(mid)
    return sorted(set(out))


def fetch_anthropic_model_ids(api_key: str, timeout: float = 45.0) -> List[str]:
    key = (api_key or "").strip()
    if not key:
        return []
    r = requests.get(
        "https://api.anthropic.com/v1/models",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        params={"limit": 1000},
        timeout=timeout,
    )
    r.raise_for_status()
    payload = r.json()
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    out: List[str] = []
    for m in rows:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id") or "").strip()
        if mid and "claude" in mid.lower():
            out.append(mid)
    return sorted(set(out))

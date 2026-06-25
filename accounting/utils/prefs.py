import json
from pathlib import Path
from typing import Any, Dict, Optional


def _prefs_path() -> Path:
    # 存在專案根目錄下，避免依賴部署環境的工作目錄
    root = Path(__file__).resolve().parents[1]
    return root / "user_prefs.json"


def _read_all() -> Dict[str, Any]:
    p = _prefs_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_all(data: Dict[str, Any]) -> None:
    p = _prefs_path()
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _user_key(user: Dict[str, Any]) -> str:
    # 以「org:name」作為最小可用識別
    org = str(user.get("org", "")).strip()
    name = str(user.get("name", "")).strip()
    return f"{org}:{name}".strip(":")


def load_theme(user: Dict[str, Any]) -> Optional[Dict[str, str]]:
    all_prefs = _read_all()
    key = _user_key(user)
    theme = all_prefs.get(key, {}).get("theme")
    return theme if isinstance(theme, dict) else None


def save_theme(user: Dict[str, Any], theme: Dict[str, str]) -> None:
    all_prefs = _read_all()
    key = _user_key(user)
    all_prefs.setdefault(key, {})
    all_prefs[key]["theme"] = theme
    _write_all(all_prefs)


def load_llm_api_key(user: Dict[str, Any]) -> Optional[str]:
    all_prefs = _read_all()
    key = _user_key(user)
    v = all_prefs.get(key, {}).get("llm_api_key")
    return v if isinstance(v, str) and v.strip() else None


def save_llm_api_key(user: Dict[str, Any], api_key: str) -> None:
    all_prefs = _read_all()
    key = _user_key(user)
    all_prefs.setdefault(key, {})
    all_prefs[key]["llm_api_key"] = api_key
    _write_all(all_prefs)


def load_llm_api_keys(user: Dict[str, Any]) -> Dict[str, str]:
    """
    回傳使用者各 LLM 的 API key（例：openai / anthropic / google）。
    兼容舊版只存單一 llm_api_key 的情況：會回填到 openai。
    """
    all_prefs = _read_all()
    key = _user_key(user)
    raw = all_prefs.get(key, {}).get("llm_api_keys")
    out: Dict[str, str] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(k, str) and isinstance(v, str) and v.strip():
                out[k.strip().lower()] = v

    legacy = all_prefs.get(key, {}).get("llm_api_key")
    if isinstance(legacy, str) and legacy.strip():
        out.setdefault("openai", legacy)
    return out


def save_llm_api_key_for(user: Dict[str, Any], llm_id: str, api_key: str) -> None:
    all_prefs = _read_all()
    key = _user_key(user)
    all_prefs.setdefault(key, {})
    llm_id_norm = str(llm_id or "").strip().lower()
    if not llm_id_norm:
        llm_id_norm = "openai"

    bucket = all_prefs[key].get("llm_api_keys")
    if not isinstance(bucket, dict):
        bucket = {}
    bucket[llm_id_norm] = str(api_key or "")
    all_prefs[key]["llm_api_keys"] = bucket
    _write_all(all_prefs)


def load_llm_model_for(user: Dict[str, Any], llm_id: str) -> Optional[str]:
    """
    讀取使用者偏好的模型名稱（例如 Gemini：`models/gemini-3-flash`）。
    """
    all_prefs = _read_all()
    key = _user_key(user)
    llm_id_norm = str(llm_id or "").strip().lower()
    v = all_prefs.get(key, {}).get("llm_models", {}).get(llm_id_norm)
    return v if isinstance(v, str) and v.strip() else None


def save_llm_model_for(user: Dict[str, Any], llm_id: str, model_name: str) -> None:
    """
    儲存使用者偏好的模型名稱（不會影響 API key）。
    """
    all_prefs = _read_all()
    key = _user_key(user)
    all_prefs.setdefault(key, {})
    llm_id_norm = str(llm_id or "").strip().lower()
    if not llm_id_norm:
        llm_id_norm = "google"

    bucket = all_prefs[key].get("llm_models")
    if not isinstance(bucket, dict):
        bucket = {}
    bucket[llm_id_norm] = str(model_name or "").strip()
    all_prefs[key]["llm_models"] = bucket
    _write_all(all_prefs)


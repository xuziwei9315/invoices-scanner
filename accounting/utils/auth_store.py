"""
登入狀態本機持久化：僅供同一瀏覽器分頁內 F5 重新整理還原（須與 auth_tab 一致）。
關閉分頁後 sessionStorage 清空，無法還原登入。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[1]
_SESSION_FILE = _ROOT / ".auth_session.json"

AuthSessionLoaded = Tuple[Dict[str, Any], int, str, int]


def save_auth_session(
    user: Dict[str, Any],
    expires_at: int,
    browser_tab_id: str,
    last_activity_at: int,
) -> None:
    payload = {
        "user": dict(user or {}),
        "expires_at": int(expires_at),
        "browser_tab_id": str(browser_tab_id or ""),
        "last_activity_at": int(last_activity_at),
    }
    try:
        _SESSION_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def load_auth_session() -> Optional[AuthSessionLoaded]:
    if not _SESSION_FILE.exists():
        return None
    try:
        data = json.loads(_SESSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    user = data.get("user")
    expires_at = data.get("expires_at")
    browser_tab_id = data.get("browser_tab_id")
    last_activity_at = data.get("last_activity_at")
    if not isinstance(user, dict) or expires_at is None:
        return None
    if not browser_tab_id:
        return None
    try:
        return (
            user,
            int(expires_at),
            str(browser_tab_id),
            int(last_activity_at if last_activity_at is not None else expires_at),
        )
    except (TypeError, ValueError):
        return None


def clear_auth_session() -> None:
    try:
        if _SESSION_FILE.exists():
            _SESSION_FILE.unlink()
    except Exception:
        pass

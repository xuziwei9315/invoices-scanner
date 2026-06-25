import time
from typing import Any, Dict, Optional

import streamlit as st

from utils.auth_browser import (
    clear_browser_tab_client,
    ensure_browser_tab_id,
    get_browser_tab_id,
)
from utils.auth_store import clear_auth_session, load_auth_session, save_auth_session

# 閒置超過此秒數未操作即自動登出
SESSION_IDLE_SECONDS = 300


def _now_ts() -> int:
    return int(time.time())


def _set_logout_reason(reason: str) -> None:
    st.session_state["auth_logout_reason"] = reason


def _browser_tab_matches() -> bool:
    auth = st.session_state.get("auth") or {}
    stored_tab = str(auth.get("browser_tab_id") or "").strip()
    current = get_browser_tab_id()
    if not stored_tab or not current:
        return False
    return stored_tab == current


def is_logged_in() -> bool:
    auth = st.session_state.get("auth") or {}
    if not auth.get("logged_in"):
        return False
    expires_at = auth.get("expires_at")
    if not expires_at:
        return False
    if _now_ts() >= int(expires_at):
        return False
    if not _browser_tab_matches():
        return False
    return True


def _apply_auth(user: Dict[str, Any], expires_at: int, browser_tab_id: str) -> None:
    st.session_state["user"] = user
    st.session_state["auth"] = {
        "logged_in": True,
        "expires_at": int(expires_at),
        "browser_tab_id": str(browser_tab_id),
    }


def touch_auth_session() -> None:
    """使用者有操作時延長閒置期限，並寫回本機（供 F5 還原）。"""
    user = st.session_state.get("user")
    auth = st.session_state.get("auth") or {}
    tab_id = str(auth.get("browser_tab_id") or "") or (get_browser_tab_id() or "")
    if not user or not tab_id or not is_logged_in():
        return
    now = _now_ts()
    exp = now + SESSION_IDLE_SECONDS
    _apply_auth(user, exp, tab_id)
    save_auth_session(user, exp, tab_id, now)


def try_restore_auth_from_storage() -> bool:
    """從本機檔還原登入（僅限同一瀏覽器分頁且未逾閒置時間）。"""
    loaded = load_auth_session()
    if not loaded:
        return False
    user, expires_at, browser_tab_id, _last_activity = loaded

    current_tab = get_browser_tab_id()
    if not current_tab or current_tab != browser_tab_id:
        clear_auth_session()
        _set_logout_reason("session_closed")
        return False

    if _now_ts() >= int(expires_at):
        clear_auth_session()
        _set_logout_reason("idle")
        return False

    _apply_auth(user, expires_at, browser_tab_id)
    if st.session_state.get("page") in (None, "login"):
        st.session_state["page"] = "dashboard"
    return True


def _force_logout_state(reason: Optional[str] = None) -> None:
    if reason:
        _set_logout_reason(reason)
    clear_auth_session()
    clear_browser_tab_client()
    st.session_state["auth"] = {"logged_in": False, "expires_at": None, "browser_tab_id": None}
    st.session_state["user"] = None
    st.session_state["page"] = "login"


def require_login() -> bool:
    """
    回傳 True 表示已登入且未過期；False 表示需要顯示登入頁。
    """
    if is_logged_in():
        touch_auth_session()
        return True

    auth = st.session_state.get("auth") or {}
    if auth.get("logged_in") and not is_logged_in():
        reason = "idle" if _now_ts() >= int(auth.get("expires_at") or 0) else "session_closed"
        _force_logout_state(reason)
        return False

    if try_restore_auth_from_storage():
        touch_auth_session()
        return True

    return False


def login_success(user: Dict[str, Any]) -> None:
    tab_id = ensure_browser_tab_id()
    now = _now_ts()
    exp = now + SESSION_IDLE_SECONDS
    _apply_auth(user, exp, tab_id)
    save_auth_session(user, exp, tab_id, now)
    st.session_state.pop("auth_logout_reason", None)
    st.session_state["page"] = "dashboard"


def logout() -> None:
    _force_logout_state()


def session_expires_at() -> Optional[int]:
    """目前登入工作階段的到期時間戳（Unix 秒），未登入則為 None。"""
    auth = st.session_state.get("auth") or {}
    if not auth.get("logged_in"):
        return None
    raw = auth.get("expires_at")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None

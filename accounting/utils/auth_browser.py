"""
瀏覽器分頁工作階段：以 sessionStorage + URL query 綁定登入狀態。
關閉分頁後 sessionStorage 清空，無法與伺服器端登入檔對應，即視為已登出。
"""
from __future__ import annotations

import json
import uuid
from typing import Optional

import streamlit as st

AUTH_TAB_QUERY_KEY = "auth_tab"
_SESSION_STORAGE_KEY = "inv_scanner_auth_tab"
_IDLE_ACTIVITY_KEY = "inv_scanner_last_activity"


def _tab_sync_script() -> str:
    """僅同步 sessionStorage，不 reload（避免與伺服器 ensure_browser_tab_id 衝突造成無限重整）。"""
    return f"""
(function() {{
  const QKEY = {json.dumps(AUTH_TAB_QUERY_KEY)};
  const SKEY = {json.dumps(_SESSION_STORAGE_KEY)};
  const win = window.parent;
  const url = new URL(win.location.href);
  const param = url.searchParams.get(QKEY);
  if (param) {{
    win.sessionStorage.setItem(SKEY, param);
    return;
  }}
  const stored = win.sessionStorage.getItem(SKEY);
  if (stored) {{
    url.searchParams.set(QKEY, stored);
    win.history.replaceState({{}}, "", url.toString());
  }}
}})();
"""


def _idle_watchdog_script(idle_seconds: int, expires_at: int) -> str:
    """到期時重整；每次 rerun 重設 parent 計時器以配合伺服器延長的 expires_at。"""
    idle_ms = max(1, int(idle_seconds)) * 1000
    expires_ms = max(0, int(expires_at)) * 1000
    timer_key = json.dumps(_IDLE_ACTIVITY_KEY + "_timer")
    return f"""
(function() {{
  const EXPIRES_MS = {expires_ms};
  const IDLE_MS = {idle_ms};
  const win = window.parent;
  const TIMER_KEY = {timer_key};
  if (win[TIMER_KEY]) {{
    win.clearTimeout(win[TIMER_KEY]);
    win[TIMER_KEY] = null;
  }}
  const target = EXPIRES_MS > 0 ? EXPIRES_MS : (Date.now() + IDLE_MS);
  const wait = Math.max(1000, target - Date.now());
  win[TIMER_KEY] = win.setTimeout(function() {{
  win[TIMER_KEY] = null;
    if (Date.now() >= target) win.location.reload();
  }}, wait);
}})();
"""


def _embed_script(script_body: str) -> None:
    """以 st.iframe 嵌入腳本（取代已棄用的 st.components.v1.html）。"""
    st.iframe(
        f"""<!DOCTYPE html><html><head><style>
html, body {{ margin: 0; padding: 0; width: 1px; height: 1px; overflow: hidden; }}
</style></head><body><script>{script_body}</script></body></html>""",
        height=1,
        width=1,
        tab_index=-1,
    )


def render_auth_client_scripts(
    *,
    idle_seconds: Optional[int] = None,
    expires_at: Optional[int] = None,
) -> None:
    """
    單一 iframe 執行瀏覽器端腳本（分頁同步；已登入時可含閒置登出監看）。
    """
    parts = [_tab_sync_script()]
    if idle_seconds is not None and expires_at is not None:
        parts.append(_idle_watchdog_script(idle_seconds, expires_at))
    _embed_script("\n".join(parts))


def render_browser_tab_sync() -> None:
    """同步 sessionStorage 與 URL `auth_tab`（相容舊呼叫）。"""
    render_auth_client_scripts()


def get_browser_tab_id() -> Optional[str]:
    raw = st.query_params.get(AUTH_TAB_QUERY_KEY)
    if raw is None:
        return None
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    s = str(raw or "").strip()
    return s or None


def ensure_browser_tab_id() -> str:
    """取得目前分頁的 tab id；若 URL 尚無則產生並寫入 query（供登入綁定）。"""
    existing = get_browser_tab_id()
    if existing:
        return existing
    new_id = str(uuid.uuid4())
    st.query_params[AUTH_TAB_QUERY_KEY] = new_id
    return new_id


def render_idle_logout_watchdog(idle_seconds: int, expires_at: int) -> None:
    """瀏覽器端閒置登出（相容舊呼叫；請改用 render_auth_client_scripts）。"""
    render_auth_client_scripts(idle_seconds=idle_seconds, expires_at=expires_at)


def clear_browser_tab_client() -> None:
    """登出時清除 URL 參數與瀏覽器 sessionStorage。"""
    try:
        del st.query_params[AUTH_TAB_QUERY_KEY]
    except KeyError:
        pass
    _embed_script(
        f"""
(function() {{
  const SKEY = {json.dumps(_SESSION_STORAGE_KEY)};
  const ACT_KEY = {json.dumps(_IDLE_ACTIVITY_KEY)};
  const win = window.parent;
  win.sessionStorage.removeItem(SKEY);
  win.sessionStorage.removeItem(ACT_KEY);
  const TIMER_KEY = {json.dumps(_IDLE_ACTIVITY_KEY + "_timer")};
  if (win[TIMER_KEY]) {{
    win.clearTimeout(win[TIMER_KEY]);
    win[TIMER_KEY] = null;
  }}
}})();
        """
    )

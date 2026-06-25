import streamlit as st
from contextlib import contextmanager
from typing import List, Tuple
from styles import SECONDARY  # default token
from utils.auth import is_logged_in, logout

def header(title: str, subtitle: str):
    st.markdown(f"<div class='h1'>{title}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='sub'>{subtitle}</div>", unsafe_allow_html=True)
    st.divider()

@contextmanager
def card():
    """
    Streamlit 的每個 widget 都是獨立區塊，不能用前後 <div> 來包覆。
    這裡用真正的 container 形成 DOM 包覆，再由 CSS 統一渲染成卡片外觀。
    """
    try:
        c = st.container(border=True)
    except TypeError:
        # 舊版 Streamlit 沒有 border 參數時的降級
        c = st.container()

    with c:
        yield

def sidebar() -> str:
    st.sidebar.markdown(
        """
        <div class="sidebar-header">
          <div class="sidebar-logo">AI</div>
          <div>
            <div class="sidebar-title">發票辨識智慧系統</div>
            <div class="sidebar-sub">Invoice Intelligence · UI Prototype</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.sidebar.markdown("<div class='nav-label'>功能選單</div>", unsafe_allow_html=True)

    # 未登入：不顯示功能選單（避免誤操作/看到資料）
    if not is_logged_in():
        st.sidebar.info("請先登入。")
        return "login"

    pages: List[Tuple[str, str, str]] = [
        ("dashboard", "儀表板",    ":material/dashboard:"),
        ("analyze",   "發票分析",  ":material/receipt_long:"),
        ("query",     "資料查詢",  ":material/search:"),
        ("reports",   "報表中心",  ":material/assessment:"),
        ("settings",  "系統設定",  ":material/settings:"),
    ]

    for key, label, icon in pages:
        # 這就是你核心的樣式判斷邏輯
        cls = "nav-button nav-button-active" if st.session_state["page"] == key else "nav-button"
        st.sidebar.markdown(f"<div class='{cls}'>", unsafe_allow_html=True)
        if st.sidebar.button(label, key=f"nav_{key}", icon=icon, use_container_width=True):
            st.session_state["page"] = key
            st.rerun()
        st.sidebar.markdown("</div>", unsafe_allow_html=True)

    st.sidebar.markdown(
        '<div class="sidebar-footer-anchor" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )
    u = st.session_state.get("user") or {"name": "—", "role": "—", "org": "—"}
    col_user, col_logout = st.sidebar.columns([4.6, 1.35], gap="small", vertical_alignment="center")
    with col_user:
        st.markdown(
            f"""
            <div class="sidebar-user">
              <div class="muted">使用者</div>
              <div class="name">{u["name"]}</div>
              <div class="role">{u["role"]} · {u["org"]}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col_logout:
        st.markdown("<div class='sidebar-logout'>", unsafe_allow_html=True)
        clicked = st.button(
            " ",
            key="nav_logout",
            icon=":material/logout:",
            help="登出",
            use_container_width=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
        if clicked:
            logout()
            st.rerun()
    return st.session_state["page"]

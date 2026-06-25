import streamlit as st

from utils.layout import card
from utils.database import verify_login
from utils.auth import login_success


def render_login():
    st.markdown(
        '<div class="login-page-anchor" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="login-deco" aria-hidden="true">
          <span class="login-shape s1"></span>
          <span class="login-shape s2"></span>
          <span class="login-shape s3"></span>
          <span class="login-shape s4"></span>
          <span class="login-shape s5"></span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="login-hero">
          <div class="login-brand-mark">AI</div>
          <div class="login-sys-title">發票辨識智慧系統</div>
          <div class="login-sys-tagline">Invoice Intelligence · 智慧分析與管理</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    sb = st.session_state.get("supabase")
    if sb is None:
        st.error("目前無法連線資料庫（Supabase）。請先到「系統設定」確認 secrets 與連線。")
        return

    # 中欄略寬於極窄版，整體仍比全寬收斂
    _, center, _ = st.columns([1.72, 1.92, 1.72])
    with center:
        with card():
            _reason = st.session_state.pop("auth_logout_reason", None)
            if _reason == "idle":
                st.warning("已超過 5 分鐘未操作，系統已自動登出，請重新登入。")
            elif _reason == "session_closed":
                st.info("瀏覽器分頁已關閉或工作階段已結束，請重新登入。")

            st.markdown(
                '<div class="login-card-title">登入</div>'
                '<div class="login-card-desc">請先登入才能使用系統功能。</div>',
                unsafe_allow_html=True,
            )
            with st.form("login_form", clear_on_submit=False, enter_to_submit=False):
                username = st.text_input("帳號", value="", placeholder="user name")
                password = st.text_input(
                    "密碼",
                    value="",
                    type="password",
                    placeholder="password",
                    key="login_password",
                )
                company_tax_id = st.text_input(
                    "公司統一編號",
                    value="",
                    placeholder="統編（8 碼）",
                )
                submitted = st.form_submit_button("登入", type="primary", use_container_width=True)

            if submitted:
                user, err = verify_login(
                    sb,
                    username=username.strip(),
                    password=password,
                    company_tax_id_input=company_tax_id,
                )
                if user:
                    login_success(user)
                    st.success("登入成功。")
                    st.rerun()
                else:
                    st.error(err or "登入失敗。")

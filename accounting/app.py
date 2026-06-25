import streamlit as st
import os
from styles import inject_css
from utils.data_tools import init_state
from utils.layout import sidebar  # 引入你剛才定義的 sidebar
from utils.auth import SESSION_IDLE_SECONDS, require_login, session_expires_at
from utils.auth_browser import ensure_browser_tab_id, render_auth_client_scripts
from views.dashboard import render_dashboard
from views.analyze import render_analyze
from views.query import render_query
from views.reports import render_reports
from views.settings import render_settings
from views.login import render_login

# 1. Page Config
st.set_page_config(
    page_title="發票辨識智慧系統",
    page_icon=":material/receipt_long:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 2. 初始化 Session State (包含 page, user, invoices 等)
init_state()

# 3. 注入 CSS 樣式
inject_css()

# 3.1 瀏覽器分頁 id（伺服器端先寫入 URL，腳本僅同步 sessionStorage）
ensure_browser_tab_id()

# 4. 登入守門：未登入/逾期只顯示登入頁
_logged_in = require_login()
if not _logged_in:
    render_login()
    render_auth_client_scripts()
    st.stop()

# 5. 執行 Sidebar 並獲取當前頁面
page = sidebar()

# 6. 路由導航
if page == "dashboard":
    render_dashboard()
elif page == "analyze":
    render_analyze()
elif page == "query":
    render_query()
elif page == "reports":
    render_reports()
elif page == "settings":
    render_settings()
elif page == "login":
    render_login()

# 7. 分頁同步 + 閒置登出（放頁面底部，避免主內容頂部留白）
_exp = session_expires_at()
render_auth_client_scripts(
    idle_seconds=SESSION_IDLE_SECONDS if _exp is not None else None,
    expires_at=_exp,
)

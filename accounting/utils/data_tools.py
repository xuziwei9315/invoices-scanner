import io
import random
import pandas as pd
import streamlit as st
from datetime import date, datetime, timedelta
from typing import List, Dict, Any
from utils.database import get_supabase, fetch_invoices_from_supabase
from utils.prefs import load_theme, load_llm_api_key
from styles import PRIMARY, SECONDARY, BG, ALERT



def df_to_excel_bytes(df: pd.DataFrame, sheet_name: str = "data") -> bytes:
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    return out.getvalue()

def init_state():
    """初始化 Session State，嚴格從 Supabase 抓取"""
    # supabase client：若先前初始化失敗會留下 None，這裡要允許重建（例如剛安裝 supabase 套件、或 secrets 修正後）
    if ("supabase" not in st.session_state) or (st.session_state.get("supabase") is None):
        st.session_state["supabase"] = get_supabase()
    
    if "invoices" not in st.session_state:
        sb = st.session_state["supabase"]
        if sb:
            # 嘗試抓取
            df = fetch_invoices_from_supabase(sb)
            if not df.empty:
                st.session_state["invoices"] = df
                st.session_state["data_source"] = "supabase"
            else:
                # 這裡不再給 mock_invoices，給一個空表格並警告
                st.session_state["invoices"] = pd.DataFrame() 
                st.session_state["data_source"] = "database_empty"
        else:
            # 連線對象根本沒建立成功
            st.session_state["invoices"] = pd.DataFrame()
            st.session_state["data_source"] = "no_connection"

    if "page" not in st.session_state:
        st.session_state["page"] = "dashboard"
    # user/auth: 由登入流程決定；未登入時不自動塞入假資料，避免「看起來已登入」
    if "user" not in st.session_state:
        st.session_state["user"] = None
    if "auth" not in st.session_state:
        st.session_state["auth"] = {"logged_in": False, "expires_at": None}
    if "ai_status" not in st.session_state:
        st.session_state["ai_status"] = {"running": True, "latency_ms": 820, "updated_at": "2026-04-28"}

    # theme: 讀取使用者偏好（若沒有就用預設）
    if "theme" not in st.session_state:
        u = st.session_state.get("user") or {}
        saved = load_theme(u) if u else None
        st.session_state["theme"] = (
            saved
            if saved
            else {"primary": PRIMARY, "secondary": SECONDARY, "bg": BG, "alert": ALERT}
        )

    if "llm_api_key" not in st.session_state:
        u = st.session_state.get("user") or {}
        st.session_state["llm_api_key"] = load_llm_api_key(u) if u else ""

    
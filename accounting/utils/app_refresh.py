"""上傳／儲存後同步刷新 session 內的發票與進項憑證快取。"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from utils.account_chart import invalidate_account_chart_cache
from utils.database import (
    fetch_input_voucher_details_from_supabase,
    fetch_invoices_from_supabase,
)
from utils.user_tax import login_buyer_tax_id, login_user_name


def refresh_invoice_caches(sb=None) -> None:
    client = sb if sb is not None else st.session_state.get("supabase")
    if client is None:
        return
    try:
        df = fetch_invoices_from_supabase(client)
        st.session_state["invoices"] = df if df is not None else pd.DataFrame()
        st.session_state["data_source"] = "supabase" if not st.session_state["invoices"].empty else "database_empty"
    except Exception:
        pass
    try:
        tid = login_buyer_tax_id()
        uname = login_user_name()
        st.session_state["input_voucher_details"] = fetch_input_voucher_details_from_supabase(
            client,
            buyer_tax_id=tid or None,
            user_name=uname or None,
        )
    except Exception:
        pass
    invalidate_account_chart_cache()

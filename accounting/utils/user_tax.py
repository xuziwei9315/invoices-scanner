"""登入使用者買方統編（與登入時驗證之公司統編一致）。"""
from __future__ import annotations

from typing import Any, Dict, Optional

import streamlit as st

from utils.invoice_fmt import normalize_buyer_tax_id


def login_user_name(user: Optional[Dict[str, Any]] = None) -> str:
    """登入者帳號名稱（對應 users.name / 登入帳號）。"""
    u = user if user is not None else (st.session_state.get("user") or {})
    return str(u.get("username") or u.get("name") or "").strip()


def login_buyer_tax_id(user: Optional[Dict[str, Any]] = None) -> str:
    u = user if user is not None else (st.session_state.get("user") or {})
    return normalize_buyer_tax_id(
        u.get("verified_company_tax_id")
        or u.get("buyer_tax_id")
        or u.get("tax_id")
        or u.get("org_tax_id")
        or ""
    )

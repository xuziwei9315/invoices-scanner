"""
科目對照表：從 Supabase 讀取，供發票分析（會計科目）與匯出（借方項目＝科目編號）。

表名：環境變數／secrets 的 ACCOUNT_CHART_TABLE，否則會嘗試「科目對照表」、account_chart 等。
欄位別名：科目名稱／科目編號（與常見英文欄位 name、code 等）。
"""
from __future__ import annotations

import difflib
from typing import Any, Dict, List

import streamlit as st


# 常見英文／中文欄位別名（若表有資料但對不到名稱，多半是欄位名不在此清單）
_NAME_KEYS = (
    "name",
    "subject_name",
    "account_name",
    "account_title",
    "title",
    "subject",
    "科目名稱",
    "會計科目名稱",
    "會計科目",
    "名稱",
    "科目",
)
_CODE_KEYS = (
    "code",
    "subject_code",
    "account_code",
    "account_no",
    "科目編號",
    "科目代碼",
    "會計科目代碼",
    "編號",
    "代碼",
)


def _row_name(r: Dict[str, Any]) -> str:
    for k in _NAME_KEYS:
        v = r.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _row_code(r: Dict[str, Any]) -> str:
    for k in _CODE_KEYS:
        v = r.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def get_chart_rows(force_reload: bool = False) -> List[Dict[str, Any]]:
    """
    讀取並快取科目對照表。
    - 僅在查詢成功時快取；若 API 失敗，下次進入頁面會自動重試（不會把失誤當成「空表」永久快取）。
    """
    key = "account_chart_rows"
    meta_key = "account_chart_fetch_meta"
    if (
        not force_reload
        and st.session_state.get(meta_key, {}).get("success") is True
        and key in st.session_state
        and isinstance(st.session_state[key], list)
    ):
        return list(st.session_state[key])

    sb = st.session_state.get("supabase")
    if not sb:
        st.session_state[key] = []
        st.session_state[meta_key] = {
            "success": False,
            "error": "無 Supabase 連線（請確認已登入且系統設定可連線）",
            "table": "",
            "row_count": 0,
            "name_cols_hit": 0,
        }
        return []

    try:
        from utils.database import fetch_account_chart_detailed

        rows, err, table = fetch_account_chart_detailed(sb)
    except Exception as e:
        rows, err, table = [], str(e), ""

    name_hits = sum(1 for r in rows if _row_name(r))
    if err:
        st.session_state[key] = []
        st.session_state[meta_key] = {
            "success": False,
            "error": err,
            "table": table,
            "row_count": 0,
            "name_cols_hit": 0,
        }
        return []

    st.session_state[key] = rows
    st.session_state[meta_key] = {
        "success": True,
        "error": "",
        "table": table,
        "row_count": len(rows),
        "name_cols_hit": name_hits,
    }
    if rows and name_hits == 0:
        st.session_state[meta_key]["error"] = (
            f"已讀取表「{table}」共 {len(rows)} 筆，但找不到科目「名稱」欄位（請確認欄位為 name／科目名稱 等）。"
        )
    return rows


def get_account_chart_status() -> Dict[str, Any]:
    """供 UI 顯示最近一次載入科目表的結果。"""
    return dict(st.session_state.get("account_chart_fetch_meta") or {})


def invalidate_account_chart_cache() -> None:
    st.session_state.pop("account_chart_rows", None)
    st.session_state.pop("account_chart_fetch_meta", None)


def chart_names_sorted(rows: List[Dict[str, Any]]) -> List[str]:
    names = [_row_name(r) for r in rows if _row_name(r)]
    return sorted(set(names))


def _pick_best_ratio(query: str, names: List[str], min_ratio: float) -> str:
    if not query or not names:
        return ""
    q = query.strip()
    qcf = q.casefold()
    for n in names:
        if n.casefold() == qcf:
            return n
    # 提示字串為某科目名稱之子字串（至少 3 字，避免「費」等過短誤判）
    if len(q) >= 3:
        inside = [n for n in names if q in n]
        if len(inside) == 1:
            return inside[0]
        if len(inside) > 1:
            inside.sort(key=len)
            return inside[0]
    best, score = "", 0.0
    for n in names:
        r = difflib.SequenceMatcher(None, q, n).ratio()
        if r > score:
            best, score = n, r
    if score >= min_ratio:
        return best
    close = difflib.get_close_matches(q, names, n=1, cutoff=max(0.3, min_ratio - 0.08))
    return close[0] if close else ""


def best_match_account_name(
    hint: str,
    rows: List[Dict[str, Any]],
    *,
    desc: str = "",
) -> str:
    """
    依 AI 建議的科目字串（hint），在對照表科目名稱中選最適合一筆（模糊比對）。
    若 hint 對不到且提供品名／備註 desc，再以 desc 輔助對照（門檻較高以免誤判）。
    對照表為空或皆低於門檻時回傳空字串。
    """
    names = chart_names_sorted(rows)
    if not names:
        return ""

    hint = (hint or "").strip()
    desc = (desc or "").strip()

    m = _pick_best_ratio(hint, names, 0.4)
    if m:
        return m
    if desc:
        m2 = _pick_best_ratio(desc[:240], names, 0.52 if hint else 0.45)
        if m2:
            return m2
    return ""


def code_for_account_name(rows: List[Dict[str, Any]], canonical_name: str) -> str:
    """依對照表內之正式科目名稱回傳科目編號（借方項目）。"""
    target = (canonical_name or "").strip()
    if not target:
        return ""
    for r in rows:
        if _row_name(r) == target:
            return _row_code(r)
    return ""

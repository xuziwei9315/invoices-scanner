import streamlit as st
import pandas as pd
from datetime import date

from utils.layout import header, card
from utils.database import fetch_input_voucher_details_from_supabase, input_voucher_detail_table_name
from utils.user_tax import login_buyer_tax_id, login_user_name
from utils.submission_period import (
    attribution_bounds_from_voucher_row,
    year_month_key,
)


def _default_attribution_range(df: pd.DataFrame) -> tuple[date, date]:
    """依資料列所屬期間推算預設起迄；無資料則今年 1 月～當月。"""
    today = date.today()
    if df is None or df.empty:
        return date(today.year, 1, 1), today
    starts: list[date] = []
    ends: list[date] = []
    for _, row in df.iterrows():
        s, e = attribution_bounds_from_voucher_row(row)
        if s:
            starts.append(s)
        if e:
            ends.append(e)
        elif s:
            ends.append(s)
    if not starts:
        return date(today.year, 1, 1), today
    return min(starts), max(ends)


def _filter_by_attribution_period(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """篩選所屬(起)～所屬(迄)與選定月份區間有交集的列。"""
    if df is None or df.empty:
        return df
    fs = year_month_key(date(start.year, start.month, 1))
    fe = year_month_key(date(end.year, end.month, 1))
    if fe < fs:
        fs, fe = fe, fs

    def _row_in_range(row: pd.Series) -> bool:
        s, e = attribution_bounds_from_voucher_row(row)
        if s is None or e is None:
            return True
        ks, ke = year_month_key(s), year_month_key(e)
        return ks <= fe and ke >= fs

    mask = df.apply(_row_in_range, axis=1)
    return df.loc[mask].copy()


def render_query():
    header(
        "資料查詢",
        "查詢已上傳至「進項憑證明細」、且買方統編與登入帳號一致之憑證。",
    )

    tid = login_buyer_tax_id()
    uname = login_user_name()
    if not tid:
        st.warning("無法取得登入公司統編，請重新登入並確認已綁定公司。")
        return

    sb = st.session_state.get("supabase")
    if sb is None:
        st.warning("目前無法連線資料庫，無法查詢進項憑證明細。")
        return

    tbl = input_voucher_detail_table_name()
    user_label = uname or "—"
    st.caption(f"登入帳號：{user_label}　·　買方統編：{tid}　·　資料表：{tbl}")

    op_left, op_right = st.columns([8, 2], gap="small", vertical_alignment="center")
    with op_right:
        if st.button("🔄 從雲端重新整理", use_container_width=True):
            df_fresh = fetch_input_voucher_details_from_supabase(
                sb, buyer_tax_id=tid, user_name=uname or None
            )
            st.session_state["input_voucher_details"] = df_fresh
            st.success("資料已更新")
            st.rerun()

    df = st.session_state.get("input_voucher_details")
    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        df = fetch_input_voucher_details_from_supabase(
            sb, buyer_tax_id=tid, user_name=uname or None
        )
        st.session_state["input_voucher_details"] = df

    if df is None or df.empty:
        st.info(
            f"尚無符合 **{user_label}**／買方統編 **{tid}** 的進項憑證明細。"
            "請先在報表中心完成「上傳至進項憑證明細」。"
        )
        st.caption("上傳時會寫入「買方統編」與「用戶代號」（登入帳號）；舊資料若無帳號欄位，僅依統編顯示。")
        return

    default_start, default_end = _default_attribution_range(df)

    top = st.columns([1, 1, 1], gap="large")
    with top[0]:
        start = st.date_input(
            "所屬期間（起）",
            value=default_start,
            help="對應欄位：所屬年(起)、所屬月(起)。預設含蓋目前已上傳資料之最早所屬月。",
        )
    with top[1]:
        end = st.date_input(
            "所屬期間（迄）",
            value=default_end,
            help="對應欄位：所屬年(迄)、所屬月(迄)。預設含蓋目前已上傳資料之最晚所屬月。",
        )
    with top[2]:
        min_amt = st.number_input("最低憑證金額", value=0, step=1000)

    with card():
        c1, c2 = st.columns([1, 1], gap="large")
        with c1:
            seller_kw = st.text_input("賣方統編關鍵字", value="")
        with c2:
            q = st.text_input("快速搜尋（發票號碼／摘要）", value="")

        view = _filter_by_attribution_period(df.copy(), start, end)

        amt_col = "憑證金額" if "憑證金額" in view.columns else None
        if amt_col:
            view["_amt"] = pd.to_numeric(view[amt_col], errors="coerce").fillna(0.0)
            view = view[view["_amt"] >= float(min_amt)].copy()

        if seller_kw.strip() and "賣方統編" in view.columns:
            view = view[
                view["賣方統編"].astype(str).str.contains(seller_kw.strip(), na=False)
            ].copy()

        if q.strip():
            search_cols = [
                c
                for c in (
                    "發票號碼&繳納證號碼",
                    "借方摘要",
                    "賣方統編",
                    "送件年月",
                    "扣抵否",
                    "用戶代號",
                )
                if c in view.columns
            ]
            if search_cols:
                mask = view[search_cols].apply(
                    lambda row: row.astype(str).str.contains(q, case=False).any(),
                    axis=1,
                )
                view = view[mask].copy()

        display_order = [
            "送件年月",
            "所屬年(起)",
            "所屬月(起)",
            "所屬月(迄)",
            "發票號碼&繳納證號碼",
            "日期",
            "賣方統編",
            "憑證金額",
            "稅額",
            "扣抵否",
            "憑證類別",
            "借方項目",
            "借方摘要",
            "買方統編",
            "用戶代號",
            "user_name",
        ]
        cleaned = view.drop(columns=["_amt"], errors="ignore")
        pinned = [c for c in display_order if c in cleaned.columns]
        rest = [c for c in cleaned.columns if c not in pinned]
        final_cols = pinned + rest

        st.caption(f"共 {len(cleaned)} 筆（已上傳且符合登入帳號／統編；所屬期間篩選已套用）")

        if not cleaned.empty:
            st.dataframe(
                cleaned[final_cols],
                use_container_width=True,
                height=450,
                hide_index=True,
            )
        else:
            st.info("找不到符合所屬期間或其他條件的進項憑證資料。")

        st.markdown(
            "<div class='muted' style='margin-top:8px;'>提示：點擊欄位標題可排序；起始／結束日期依「所屬年(起)／所屬月(起)」至「所屬年(迄)／所屬月(迄)」篩選，非發票交易日期。</div>",
            unsafe_allow_html=True,
        )

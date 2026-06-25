import streamlit as st
import pandas as pd
from datetime import date

from utils.layout import header, card
from utils.database import fetch_input_voucher_details_from_supabase
from utils.user_tax import login_buyer_tax_id


def _parse_roc_yyyymmdd_cell(val) -> pd.Timestamp:
    s = str(val or "").strip()
    if len(s) != 7 or not s.isdigit():
        return pd.NaT
    try:
        y = int(s[:3]) + 1911
        m, d = int(s[3:5]), int(s[5:7])
        return pd.Timestamp(date(y, m, d))
    except (TypeError, ValueError):
        return pd.NaT


def _latest_submission_slice(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    if "送件年月" in df.columns:
        s = df["送件年月"].astype(str).str.strip()
        valid = s[s.str.match(r"^\d{5,6}$", na=False)]
        if not valid.empty:
            latest = valid.max()
            return df.loc[s == latest].copy()
    for col in ("日期", "transaction_date"):
        if col not in df.columns:
            continue
        if col == "日期":
            dt = df[col].map(_parse_roc_yyyymmdd_cell)
        else:
            dt = pd.to_datetime(df[col], errors="coerce")
        if dt.notna().any():
            latest = dt.max()
            y, m = int(latest.year), int(latest.month)
            return df.loc[(dt.dt.year == y) & (dt.dt.month == m)].copy()
    return df.copy()


def _to_float_series(df: pd.DataFrame, *cols: str) -> float:
    for c in cols:
        if c in df.columns:
            return float(pd.to_numeric(df[c], errors="coerce").fillna(0.0).sum())
    return 0.0


def render_dashboard():
    header("儀表板", "依登入公司統編，彙總已上傳至進項憑證明細之憑證。")

    tid = login_buyer_tax_id()
    if not tid:
        st.warning("無法取得登入公司統編，請重新登入並確認已綁定公司。")
        return

    sb = st.session_state.get("supabase")
    if sb is None:
        st.warning("目前無法連線資料庫，無法讀取進項憑證明細。")
        return

    df_all = fetch_input_voucher_details_from_supabase(sb, buyer_tax_id=tid)
    st.session_state["input_voucher_details"] = df_all

    if df_all is None or df_all.empty:
        st.info(
            f"尚無買方統編 **{tid}** 已上傳至「進項憑證明細」的資料。"
            "請於報表中心匯出後，使用「上傳至進項憑證明細」完成入庫。"
        )
        return

    df_month = _latest_submission_slice(df_all)
    month_count = int(len(df_month))
    voucher_total = _to_float_series(df_month, "憑證金額", "含稅金額", "total_amount")
    tax_total = _to_float_series(df_month, "稅額", "tax_amount")

    if not df_month.empty and "憑證金額" in df_month.columns:
        amt_series = pd.to_numeric(df_month["憑證金額"], errors="coerce").fillna(0.0)
        highest_amount = float(amt_series.max()) if len(amt_series) else 0.0
    else:
        highest_amount = 0.0

    sub_label = ""
    if "送件年月" in df_month.columns and not df_month.empty:
        sub_label = str(df_month["送件年月"].astype(str).iloc[0]).strip()

    st.caption(f"公司統編（買方）：{tid}　·　資料來源：進項憑證明細　·　共 {len(df_all)} 筆")

    k1, k2, k3 = st.columns(3, gap="large")
    with k1:
        hint = f"送件月 {sub_label}" if sub_label else "最近送件月份"
        st.markdown(
            f"""
            <div class="kpi-tile kpi-tile-1">
              <div class='kpi-title'>本月憑證筆數</div>
              <div class='mono kpi-value'>{month_count}</div>
              <div class='kpi-hint'>{hint}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with k2:
        st.markdown(
            f"""
            <div class="kpi-tile kpi-tile-2">
              <div class='kpi-title'>憑證金額合計</div>
              <div class='mono kpi-value'>{voucher_total:,.0f}</div>
              <div class='kpi-hint'>TWD · 本月累計</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with k3:
        st.markdown(
            f"""
            <div class="kpi-tile kpi-tile-3">
              <div class='kpi-title'>稅額合計</div>
              <div class='mono kpi-value'>{tax_total:,.0f}</div>
              <div class='kpi-hint'>TWD · 本月累計</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("")

    col_chart, col_side = st.columns([1.55, 1], gap="large")

    with col_chart:
        with card():
            st.markdown("<div class='section-title'>科目摘要分布</div>", unsafe_allow_html=True)
            summary_col = None
            for c in ("借方摘要", "description", "品名/備註"):
                if c in df_month.columns:
                    summary_col = c
                    break
            amt_col = "憑證金額" if "憑證金額" in df_month.columns else None
            if summary_col and amt_col and not df_month.empty:
                grp = (
                    df_month.groupby(summary_col, dropna=False)[amt_col]
                    .apply(lambda s: pd.to_numeric(s, errors="coerce").fillna(0.0).sum())
                    .sort_values(ascending=False)
                    .head(12)
                )
                if grp.sum() > 0:
                    st.bar_chart(grp, use_container_width=True)
                else:
                    st.info("本月暫無可彙總的金額資料。")
            else:
                st.info("本月暫無摘要或金額欄位可繪圖。")

    with col_side:
        with card():
            st.markdown("<div class='section-title'>摘要提醒</div>", unsafe_allow_html=True)
            st.markdown(
                f"""
                <div class="alert-list risk-compact">
                  <div class="alert-item">
                    <strong>高金額憑證</strong>
                    本月最高憑證金額 {highest_amount:,.0f} 元，建議人工覆核。
                  </div>
                  <div class="alert-item">
                    <strong>資料範圍</strong>
                    僅顯示買方統編 {tid} 且已寫入進項憑證明細之紀錄。
                  </div>
                  <div class="alert-item">
                    <strong>筆數</strong>
                    全庫 {len(df_all)} 筆；最近送件月 {month_count} 筆。
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("")

    with card():
        st.markdown("<div class='section-title'>最近進項憑證（前 10 筆）</div>", unsafe_allow_html=True)
        show_cols = [
            c
            for c in (
                "送件年月",
                "發票號碼&繳納證號碼",
                "日期",
                "賣方統編",
                "憑證金額",
                "稅額",
                "扣抵否",
                "借方摘要",
            )
            if c in df_all.columns
        ]
        if show_cols:
            st.dataframe(df_all[show_cols].head(10), use_container_width=True, hide_index=True)
        else:
            st.dataframe(df_all.head(10), use_container_width=True, hide_index=True)

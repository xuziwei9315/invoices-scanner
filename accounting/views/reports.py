import streamlit as st
import pandas as pd
from utils.layout import header, card
from utils.invoice_export import (
    invoices_to_export_dataframe,
    EXPORT_COLUMNS,
)
from utils.database import (
    fetch_input_voucher_details_from_supabase,
    insert_input_voucher_details_from_dataframe,
    input_voucher_detail_table_name,
    delete_invoices_by_invoice_numbers,
)
from utils.user_tax import login_buyer_tax_id, login_user_name
from utils.app_refresh import refresh_invoice_caches
from utils.submission_period import parse_roc_yyyymm
from utils.voucher_file_export import export_root_path, export_vouchers_to_folders
from utils.invoice_file_archive import (
    archive_import_files_for_dataframe,
    ensure_uuids_on_dataframe,
    file_key_column,
    import_root_path,
    list_import_file_keys,
)


def _invoice_month_series(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=str)
    if "uploaded_at" in df.columns:
        date_series = df["uploaded_at"]
    elif "created_at" in df.columns:
        date_series = df["created_at"]
    else:
        return pd.Series([""] * len(df), index=df.index)
    txn_dt = pd.to_datetime(date_series, errors="coerce")
    return txn_dt.dt.strftime("%Y-%m").fillna("")


def _voucher_month_series(df: pd.DataFrame) -> pd.Series:
    """依「送件年月」（民國 YYYMM）轉成 YYYY-MM，供月份篩選與匯出選單對齊。"""
    if df is None or df.empty:
        return pd.Series(dtype=str)

    def _cell_to_month(val) -> str:
        d = parse_roc_yyyymm(str(val or "").strip())
        if d is not None:
            return d.strftime("%Y-%m")
        s = str(val or "").strip()
        if len(s) == 7 and s.isdigit():
            try:
                y = int(s[:3]) + 1911
                m = int(s[3:5])
                return f"{y:04d}-{m:02d}"
            except (TypeError, ValueError):
                pass
        return ""

    if "送件年月" in df.columns:
        return df["送件年月"].map(_cell_to_month)
    return pd.Series([""] * len(df), index=df.index)


def _merge_month_options(*series_list: pd.Series) -> list[str]:
    months: set[str] = set()
    for s in series_list:
        if s is None or len(s) == 0:
            continue
        for m in s.dropna().astype(str).tolist():
            m = str(m).strip()
            if m and m.lower() != "nan":
                months.add(m)
    return sorted(months)


def _filter_by_month(df: pd.DataFrame, month_col: str, month_choice: str) -> pd.DataFrame:
    if df is None or df.empty or month_choice == "全部":
        return df.copy() if df is not None else pd.DataFrame()
    if month_col not in df.columns:
        return df.iloc[0:0].copy()
    return df.loc[df[month_col].astype(str) == month_choice].copy()


def _render_export_feedback(suffix: str) -> None:
    """匯出結果顯示於預覽表格下方。"""
    upload_flash = st.session_state.pop(f"voucher_upload_flash_{suffix}", None)
    if upload_flash:
        st.success(str(upload_flash))

    arch = st.session_state.get(f"voucher_archive_msg_{suffix}")
    if arch and arch.get("moved"):
        st.caption(f"發票檔歸檔：{len(arch['moved'])} 個檔案已移至 exports 子資料夾。")
    if arch and arch.get("not_found"):
        nf = arch.get("not_found") or []
        if nf:
            fk_col = arch.get("file_key_column") or "uuid"
            st.warning(
                f"有 {len(nf)} 筆在 import 找不到與資料庫「{fk_col}」相同的檔案。"
                f"請將發票檔放入 `{import_root_path().resolve()}`，檔名（不含副檔名）須與資料庫欄位一致。"
            )

    imp_keys = list_import_file_keys()
    _voucher_df = st.session_state.get("input_voucher_details")
    if not isinstance(_voucher_df, pd.DataFrame):
        _voucher_df = pd.DataFrame()
    fk = file_key_column(_voucher_df)
    st.caption(
        f"發票檔待歸檔：`{import_root_path().resolve()}`（目前 {len(imp_keys)} 個檔案）。"
        "匯出時會依資料庫檔名欄位，將對應檔案移入與 Excel 相同的 exports 子資料夾。"
        + (f"比對欄位：「{fk}」。" if fk else "")
    )

    out = st.session_state.get(f"voucher_export_msg_{suffix}")
    if out:
        if out.get("errors"):
            for msg in out["errors"]:
                st.error(msg)
        if out.get("files"):
            for folder_name, fpath in zip(
                out.get("folder_names", []),
                out.get("files", []),
            ):
                st.caption(f"📁 {folder_name} → `{fpath}`")
        elif not out.get("errors"):
            st.warning("沒有產生任何檔案，請確認資料與「扣抵否」欄位。")

    st.caption(f"匯出根目錄：`{export_root_path().resolve()}`")

    if out and out.get("files"):
        n_yes = out["counts"].get("deductible", 0)
        n_no = out["counts"].get("non_deductible", 0)
        st.success(
            f"已匯出至 **{out['root']}**："
            f"已扣抵 {n_yes} 筆、未扣抵 {n_no} 筆。"
        )
        moved = out.get("moved_files") or []
        if moved:
            st.caption(
                f"已自 import 歸檔 {len(moved)} 個發票檔，"
                "與 Excel 放在同一 exports 子資料夾內。"
            )


def _preview_column_order(df: pd.DataFrame) -> list[str]:
    pinned = [c for c in EXPORT_COLUMNS if c in df.columns]
    fk = file_key_column(df)
    if fk and fk not in pinned:
        pinned.insert(0, fk)
    if "買方統編" in df.columns and "買方統編" not in pinned:
        pinned.append("買方統編")
    if "用戶代號" in df.columns and "用戶代號" not in pinned:
        pinned.append("用戶代號")
    rest = [c for c in df.columns if c not in pinned and not str(c).startswith("_")]
    return pinned + rest


def render_reports():
    header("報表中心", "匯出進項發票明細，並可上傳至雲端「進項憑證明細」。")

    tid = login_buyer_tax_id()
    uname = login_user_name()
    sb = st.session_state.get("supabase")

    raw_inv = st.session_state.get("invoices")
    if raw_inv is None:
        df_invoices = pd.DataFrame()
    else:
        df_invoices = raw_inv.copy()

    df_for_reports = df_invoices.copy()
    df_for_reports["_txn_month"] = _invoice_month_series(df_for_reports)

    df_vouchers = pd.DataFrame()
    if sb is not None and tid:
        df_vouchers = fetch_input_voucher_details_from_supabase(
            sb, buyer_tax_id=tid, user_name=uname or None
        )
        st.session_state["input_voucher_details"] = df_vouchers
    elif sb is None:
        st.warning("目前無法連線資料庫，無法讀取進項憑證明細預覽。")

    df_vouchers = df_vouchers.copy()
    df_vouchers["_txn_month"] = _voucher_month_series(df_vouchers)

    month_options = _merge_month_options(
        df_for_reports["_txn_month"],
        df_vouchers["_txn_month"],
    )

    top = st.columns([2, 1], gap="large", vertical_alignment="bottom")
    with top[0]:
        month_choice = st.selectbox(
            "選擇月份（送件年月）",
            options=["全部"] + month_options,
            index=0,
            help="依進項憑證明細的「送件年月」篩選；匯出 Excel 與下方預覽為相同範圍。",
        )
    suffix = "" if month_choice == "全部" else f"_{month_choice}"

    preview_raw = _filter_by_month(df_vouchers, "_txn_month", month_choice)
    preview_df = preview_raw.drop(columns=["_txn_month"], errors="ignore")
    preview_cols = _preview_column_order(preview_df) if not preview_df.empty else []
    export_voucher_df = (
        preview_df[preview_cols].copy()
        if preview_cols
        else preview_df.copy()
    )
    fk_col = file_key_column(preview_df)
    if fk_col and fk_col not in export_voucher_df.columns:
        export_voucher_df[fk_col] = preview_df[fk_col].values

    with top[1]:
        export_disabled = export_voucher_df.empty
        if st.button(
            "匯出至資料夾",
            type="primary",
            use_container_width=True,
            disabled=export_disabled,
            icon=":material/folder_open:",
            key=f"export_voucher_dirs_{suffix}",
        ):
            # 歸檔發票檔：以資料庫完整列（含 uuid／檔名）比對 import，不重新產生 uuid
            archive_df = preview_df.copy()
            st.session_state[f"voucher_export_msg_{suffix}"] = export_vouchers_to_folders(
                export_voucher_df,
                column_order=preview_cols or None,
                archive_df=archive_df,
            )

    df_filtered = _filter_by_month(df_for_reports, "_txn_month", month_choice)
    df_filtered_export = df_filtered.drop(columns=["_txn_month"], errors="ignore")
    export_invoice_df = (
        invoices_to_export_dataframe(
            df_filtered_export,
            st.session_state.get("user") or {},
        )
        if not df_filtered_export.empty
        else pd.DataFrame()
    )

    st.markdown("")

    tbl_label = input_voucher_detail_table_name()

    with card():
        st.markdown("<div class='section-title'>進項憑證明細預覽</div>", unsafe_allow_html=True)
        month_hint = "全部月份" if month_choice == "全部" else month_choice
        st.caption(
            f"顯示資料表「{tbl_label}」中送件月份為 **{month_hint}** 的紀錄"
            f"（依「送件年月」對應之曆月篩選）。"
        )
        if preview_df.empty:
            st.info(
                f"尚無符合所選月份的進項憑證明細。"
                if month_choice != "全部"
                else "尚無進項憑證明細資料，請先完成上傳。"
            )
        else:
            st.caption(f"共 {len(preview_df)} 筆")
            st.dataframe(
                preview_df[preview_cols] if preview_cols else preview_df,
                use_container_width=True,
                height=480,
                hide_index=True,
            )

        _render_export_feedback(suffix)

    if not export_invoice_df.empty:
        st.markdown("")
        with card():
            st.markdown("<div class='section-title'>待上傳發票明細</div>", unsafe_allow_html=True)
            st.caption(
                f"以下為發票庫待寫入「{tbl_label}」的資料，可編輯後上傳。"
            )
            edited_invoice = st.data_editor(
                export_invoice_df.copy(),
                use_container_width=True,
                height=360,
                num_rows="dynamic",
                hide_index=True,
                key=f"ved_invoice_{suffix}",
            )
            upload_cols = [
                c
                for c in edited_invoice.columns
                if c in EXPORT_COLUMNS or str(c).strip().lower() == "uuid"
            ]
            upload_df = edited_invoice[upload_cols].copy() if upload_cols else edited_invoice.copy()
            upload_df = ensure_uuids_on_dataframe(upload_df)
            if tid:
                upload_df["買方統編"] = tid
            if uname and "用戶代號" in upload_df.columns:
                upload_df["用戶代號"] = uname
            if st.button(
                "上傳至進項憑證明細",
                type="primary",
                use_container_width=False,
                icon=":material/cloud_upload:",
                key=f"upload_voucher_detail_{suffix}",
            ):
                if sb is None:
                    st.error("無 Supabase 連線，無法上傳。")
                else:
                    n, err = insert_input_voucher_details_from_dataframe(sb, upload_df)
                    if err:
                        st.error(f"上傳失敗：{err}")
                    else:
                        inv_nums: list[str] = []
                        if "發票號碼&繳納證號碼" in upload_df.columns:
                            inv_nums = [str(x) for x in upload_df["發票號碼&繳納證號碼"].tolist()]
                        _, err_del = delete_invoices_by_invoice_numbers(sb, inv_nums)
                        if err_del:
                            st.warning(
                                "進項憑證已寫入，但自 **invoices** 刪除原發票失敗："
                                f"{err_del}"
                            )
                        refresh_invoice_caches(sb)
                        arch = archive_import_files_for_dataframe(upload_df)
                        st.session_state[f"voucher_archive_msg_{suffix}"] = arch
                        wkey = f"ved_invoice_{suffix}"
                        if wkey in st.session_state:
                            try:
                                del st.session_state[wkey]
                            except Exception:
                                pass
                        moved_n = len(arch.get("moved") or [])
                        if err_del:
                            msg = f"已成功寫入 {n} 筆至「{tbl_label}」。"
                        else:
                            msg = (
                                f"已成功寫入 {n} 筆至「{tbl_label}」，並已自 **invoices** 移除對應發票。"
                            )
                        if moved_n:
                            msg += f" 已歸檔 {moved_n} 個發票檔至 exports 對應資料夾。"
                        st.session_state[f"voucher_upload_flash_{suffix}"] = msg
                        st.rerun()

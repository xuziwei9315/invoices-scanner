"""
將 invoices DataFrame 轉成會計／進項匯出用欄位順序（Excel）。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from utils.invoice_fmt import normalize_invoice_number
from utils.account_chart import get_chart_rows, best_match_account_name, code_for_account_name
from utils.submission_period import period_from_invoice_row

EXPORT_COLUMNS: List[str] = [
    "送件年月",
    "用戶代號",
    "所屬年(起)",
    "所屬月(起)",
    "所屬月(迄)",
    "憑證類別",
    "第冊數",
    "扣抵否",
    "序號(進項憑證)",
    "類別(進項憑證)",
    "憑證金額",
    "稅別",
    "稅額",
    "日期",
    "賣方統編",
    "營業稅項目類別代號",
    "供應商代號",
    "公斤數",
    "發票號碼&繳納證號碼",
    "年期別(公用事業憑證使用)",
    "公用事業註記",
    "公用事業分攤註記",
    "借方項目",
    "借方摘要",
    "貸方項目",
    "貸方摘要",
    "稅額項目",
    "稅額摘要",
]

# 寫入 Supabase「進項憑證明細」時額外允許的欄位（表內為中文欄名，非 buyer_tax_id）
INPUT_VOUCHER_DB_EXTRA_COLUMNS: List[str] = ["買方統編", "uuid"]

# PostgREST 進項憑證明細表為 integer 的欄位（編輯器常產生 5.0 / "5.0" 需轉整數）
INPUT_VOUCHER_INTEGER_COLUMNS: frozenset[str] = frozenset(
    {
        "送件年月",
        "所屬年(起)",
        "所屬月(起)",
        "所屬月(迄)",
        "憑證類別",
        "第冊數",
        "序號(進項憑證)",
        "類別(進項憑證)",
        "稅別",
        "日期",
        "賣方統編",
        "公斤數",
        "年期別(公用事業憑證使用)",
    }
)


def coerce_voucher_integer(val: Any) -> Any:
    """將儲存格轉成 integer 或 None，供寫入進項憑證明細。"""
    if val is None:
        return None
    if isinstance(val, str):
        s = val.strip()
        if not s or s.lower() in ("nan", "none", "nat"):
            return None
        try:
            f = float(s.replace(",", ""))
            if f == int(f):
                return int(f)
            return None
        except (TypeError, ValueError):
            return None
    try:
        if isinstance(val, float) and pd.isna(val):
            return None
    except Exception:
        pass
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        if val != val:
            return None
        if val == int(val):
            return int(val)
        return None
    if hasattr(val, "item") and not isinstance(val, (str, bytes)):
        try:
            return coerce_voucher_integer(val.item())
        except Exception:
            return None
    return None


def input_voucher_insert_column_names() -> frozenset[str]:
    """進項憑證明細 insert 允許欄位（與 DB 中文欄名一致）。"""
    return frozenset(EXPORT_COLUMNS) | frozenset(INPUT_VOUCHER_DB_EXTRA_COLUMNS)


def _roc_yyyymm(ts: pd.Timestamp) -> str:
    if pd.isna(ts):
        return ""
    y = int(ts.year) - 1911
    m = int(ts.month)
    return f"{y:03d}{m:02d}"


def _roc_yyyymmdd(ts: pd.Timestamp) -> str:
    if pd.isna(ts):
        return ""
    y = int(ts.year) - 1911
    return f"{y:03d}{int(ts.month):02d}{int(ts.day):02d}"


def _parse_ts(val: Any) -> pd.Timestamp:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return pd.NaT
    t = pd.to_datetime(val, errors="coerce")
    return t if not pd.isna(t) else pd.NaT


def _cell(row: pd.Series, keys: tuple[str, ...], default: Any = "") -> Any:
    for k in keys:
        if k in row.index:
            v = row[k]
            if v is None or (isinstance(v, float) and pd.isna(v)):
                continue
            if isinstance(v, str) and not v.strip():
                continue
            return v
    return default


def _voucher_type_code(invoice_type: str) -> str:
    s = str(invoice_type or "").strip().replace(" ", "")
    if s == "三聯式統一發票":
        return "1"
    if s in ("三聯式收銀機統一發票扣抵聯", "電子發票"):
        return "2"
    return ""


def _parse_deductible_tri(v: Any) -> Optional[bool]:
    """
    True = 可扣抵，False = 不可扣抵，None = 無法從此值判斷。
    注意：不可使用 bool(\"False\")，在 Python 中會為 True。
    """
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    if v is True or v is False:
        return bool(v)
    # numpy.bool_ 等：與 True/False 比較
    try:
        if v == True:  # noqa: E712
            return True
        if v == False:  # noqa: E712
            return False
    except Exception:
        pass
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if int(v) == 0:
            return False
        if int(v) == 1:
            return True
        return None
    s = str(v).strip().lower()
    if not s or s in ("nan", "none"):
        return None
    if s in ("true", "1", "yes", "y", "t", "是", "可扣抵", "可"):
        return True
    if s in ("false", "0", "no", "n", "f", "否", "不可扣抵", "不可"):
        return False
    return None


def _deduct_flag(row: pd.Series) -> str:
    """
    扣抵否：可扣抵為 Y，不可扣抵為 N；無法判斷時為空字串。
    """
    for key in ("is_deductible", "deductible"):
        if key not in row.index:
            continue
        tri = _parse_deductible_tri(row[key])
        if tri is True:
            return "Y"
        if tri is False:
            return "N"
    if "扣抵否" in row.index:
        tri = _parse_deductible_tri(row["扣抵否"])
        if tri is True:
            return "Y"
        if tri is False:
            return "N"
        s = str(row["扣抵否"] or "").strip().upper()
        if s == "Y":
            return "Y"
        if s == "N":
            return "N"
    if "可扣抵" in row.index:
        s = str(row["可扣抵"] or "").strip()
        if s in ("可扣抵", "Y", "y", "1", "是", "true", "True"):
            return "Y"
        if s in ("不可扣抵", "N", "n", "0", "否", "false", "False"):
            return "N"
    return ""


def _input_voucher_category(row: pd.Series) -> int:
    """
    類別(進項憑證)：進貨=1、費用=2、固定資產=3。
    若資料列有明確欄位則優先採用；否則依會計科目／摘要關鍵字推斷；無法判斷時預設 2（費用）。
    """
    for key in (
        "input_voucher_category",
        "進項憑證類別",
        "進項類別",
        "voucher_input_type",
    ):
        if key not in row.index:
            continue
        v = row[key]
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        s = str(v).strip()
        if not s or s.lower() in ("nan", "none"):
            continue
        if s in ("1", "進貨"):
            return 1
        if s in ("2", "費用"):
            return 2
        if s in ("3", "固定資產"):
            return 3
        try:
            n = int(float(s))
            if n in (1, 2, 3):
                return n
        except (TypeError, ValueError):
            pass

    acct = str(_cell(row, ("account", "會計科目"), default="")).strip()
    desc = str(
        _cell(row, ("description", "品名/備註", "科目摘要"), default="")
    ).strip()
    blob = f"{acct}{desc}".replace(" ", "").replace("\u3000", "")

    for kw in (
        "固定資產",
        "未完工程",
        "機械設備",
        "運輸設備",
        "辦公設備",
        "不動產",
        "建築物",
        "累計折舊",
    ):
        if kw in blob:
            return 3
    for kw in (
        "進貨",
        "進項存貨",
        "原料",
        "物料",
        "在途材料",
        "成品",
        "商品",
        "存貨",
        "原物料",
    ):
        if kw in blob:
            return 1
    return 2


def _to_float(v: Any) -> float:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return 0.0
        return float(str(v).replace(",", "").strip() or 0)
    except Exception:
        return 0.0


def _voucher_amount_for_export(ded_flag: str, taxable: float, tax_amt: float, total_amt: float) -> float:
    """
    憑證金額：不可扣抵 (N) 填含稅金額；可扣抵 (Y) 或未知填未稅（應稅）金額。
    缺欄時以 heuristics 由含稅／稅額反推。
    """
    if ded_flag == "N":
        t = float(total_amt or 0.0)
        if not t and (taxable or tax_amt):
            t = float(taxable) + float(tax_amt)
        return round(t, 2)
    tx = float(taxable or 0.0)
    if not tx and total_amt:
        tot = float(total_amt)
        if tax_amt and tot >= float(tax_amt):
            tx = round(tot - float(tax_amt), 2)
        if not tx:
            tx = round(tot / 1.05, 2)
    return round(tx, 2)


def invoices_to_export_dataframe(
    df: pd.DataFrame,
    user: Optional[Dict[str, Any]] = None,
    *,
    fallback_now: Optional[datetime] = None,
) -> pd.DataFrame:
    """
    依指定欄位順序產出匯出用 DataFrame。
    - 送件年月／所屬(起)(迄)：優先 submission_yyyymm 與所屬欄位；否則由 uploaded_at（送件月）推算；
      不應以交易日期代替所屬期間。
    - 憑證金額：可扣抵 (Y/未知) 為未稅金額；不可扣抵 (N) 為含稅金額。
    - 稅別：可扣抵時固定 5；不可扣抵 (N) 時留空。
    - 日期：交易日期轉民國年月日（例 1150510）
    - 貸方項目：1110、貸方摘要：銀行存款
    - 借方摘要：發票摘要（description / 品名備註）
    - 類別(進項憑證)：進貨=1、費用=2、固定資產=3（見 _input_voucher_category）
    - 稅額／稅別：扣抵否為「不可扣抵」(N) 時皆不填入（空白）；可扣抵 (Y) 或未知則稅別為 5、稅額為金額。
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=EXPORT_COLUMNS)

    now = fallback_now or datetime.now()
    now_ts = pd.Timestamp(now)

    u = user or {}
    user_code = str(u.get("username") or u.get("name") or u.get("id") or "").strip()

    chart_rows = get_chart_rows()

    rows_out: List[Dict[str, Any]] = []
    seq = 0

    for _, row in df.iterrows():
        seq += 1

        period = period_from_invoice_row(row)
        if period is None and fallback_now is not None:
            from utils.submission_period import compute_submission_period

            period = compute_submission_period(
                date(fallback_now.year, fallback_now.month, 1)
            )

        if period is not None:
            submission_yyyymm = str(period.get("submission_yyyymm") or "").strip()
            if not submission_yyyymm and period.get("submission_date"):
                submission_yyyymm = _roc_yyyymm(period["submission_date"])
            roc_y_start = str(period.get("attribution_year_start") or "")
            roc_m_start = str(period.get("attribution_month_start") or "")
            roc_m_end = str(period.get("attribution_month_end") or "")
        else:
            submission_yyyymm = ""
            roc_y_start = ""
            roc_m_start = ""
            roc_m_end = ""

        txn = _parse_ts(
            _cell(
                row,
                ("transaction_date", "交易日期"),
                default=None,
            )
        )
        if not pd.isna(txn):
            date_cell = _roc_yyyymmdd(txn)
        else:
            date_cell = ""

        inv_type = str(
            _cell(row, ("invoice_type", "發票類型"), default="")
        ).strip()

        taxable = _to_float(_cell(row, ("taxable_amount", "應稅金額"), default=0.0))
        tax_amt = _to_float(_cell(row, ("tax_amount", "稅額"), default=0.0))
        total_amt = _to_float(_cell(row, ("total_amount", "含稅金額"), default=0.0))
        ded_flag = _deduct_flag(row)
        voucher_amt = _voucher_amount_for_export(ded_flag, taxable, tax_amt, total_amt)
        # 不可扣抵時匯出欄位「稅額」「稅別」留空
        tax_export: Any = None if ded_flag == "N" else round(tax_amt, 2)
        tax_type_export: Any = None if ded_flag == "N" else int(5)

        inv_no = normalize_invoice_number(
            str(_cell(row, ("invoice_number", "發票號碼"), default=""))
        )

        uuid_val = str(_cell(row, ("uuid",), default="")).strip()
        if not uuid_val and inv_no:
            try:
                import streamlit as st

                mp = st.session_state.get("invoice_uuid_map") or {}
                if isinstance(mp, dict):
                    uuid_val = str(mp.get(inv_no) or "").strip()
            except Exception:
                pass

        desc = str(_cell(row, ("description", "品名/備註", "科目摘要"), default="")).strip()
        acct_raw = str(_cell(row, ("account", "會計科目"), default="")).strip()
        acct_canon = best_match_account_name(acct_raw, chart_rows, desc=desc)
        debit_item = code_for_account_name(chart_rows, acct_canon)

        rows_out.append(
            {
                "送件年月": submission_yyyymm,
                "用戶代號": user_code,
                "所屬年(起)": roc_y_start,
                "所屬月(起)": roc_m_start,
                "所屬月(迄)": roc_m_end,
                "憑證類別": _voucher_type_code(inv_type),
                "第冊數": "",
                "扣抵否": ded_flag,
                "序號(進項憑證)": seq,
                "類別(進項憑證)": _input_voucher_category(row),
                "憑證金額": voucher_amt,
                "稅別": tax_type_export,
                "稅額": tax_export,
                "日期": date_cell,
                "賣方統編": str(_cell(row, ("seller_tax_id", "賣方統編"), default="")).strip(),
                "營業稅項目類別代號": "",
                "供應商代號": "",
                "公斤數": "",
                "發票號碼&繳納證號碼": inv_no,
                "年期別(公用事業憑證使用)": "",
                "公用事業註記": "",
                "公用事業分攤註記": "",
                "借方項目": debit_item,
                "借方摘要": desc,
                "貸方項目": "1110",
                "貸方摘要": "銀行存款",
                "稅額項目": "",
                "稅額摘要": "",
            }
        )
        if uuid_val:
            rows_out[-1]["uuid"] = uuid_val

    out_cols = list(EXPORT_COLUMNS)
    if rows_out and any("uuid" in r for r in rows_out):
        out_cols.append("uuid")
    return pd.DataFrame(rows_out, columns=out_cols)


def remove_invoices_matching_voucher_export(
    df_invoices: pd.DataFrame,
    upload_voucher_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    依進項匯出表「發票號碼&繳納證號碼」欄，從發票 DataFrame 剔除對應列（上傳進項憑證明細後清掉預覽來源）。
    """
    if df_invoices is None or df_invoices.empty:
        return df_invoices if df_invoices is not None else pd.DataFrame()
    if upload_voucher_df is None or upload_voucher_df.empty:
        return df_invoices.copy()
    col = "發票號碼&繳納證號碼"
    if col not in upload_voucher_df.columns:
        return df_invoices.copy()
    nums: set[str] = set()
    for v in upload_voucher_df[col].tolist():
        n = normalize_invoice_number(str(v or ""))
        if n:
            nums.add(n)
    if not nums:
        return df_invoices.copy()
    inv_col = None
    for c in ("invoice_number", "發票號碼"):
        if c in df_invoices.columns:
            inv_col = c
            break
    if inv_col is None:
        return df_invoices.copy()
    norm_series = df_invoices[inv_col].astype(str).map(lambda x: normalize_invoice_number(x))
    mask = ~norm_series.isin(nums)
    return df_invoices.loc[mask].copy()

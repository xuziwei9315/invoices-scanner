"""
送件月份與所屬期間（起迄）計算。
所屬(起) = 送件月 - 2；所屬(迄) = 送件月 - 1（民國年、月分別計算）。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional, Tuple


def subtract_months(d: date, months: int) -> date:
    """以該月 1 日為基準往前/往後推移月份。"""
    y, m = d.year, d.month
    m -= int(months)
    while m <= 0:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return date(y, m, 1)


def _roc_year_month(d: date) -> tuple[str, str]:
    return f"{int(d.year) - 1911:03d}", f"{int(d.month):02d}"


def roc_yyyymm(d: date) -> str:
    y, m = _roc_year_month(d)
    return f"{y}{m}"


def compute_submission_period(submission: date) -> Dict[str, Any]:
    """
    submission：送件月份（建議為該月 1 日）。
    回傳供 UI、分析、匯出共用的期間字典。
    """
    sub = date(submission.year, submission.month, 1)
    start = subtract_months(sub, 2)
    end = subtract_months(sub, 1)
    y0, m0 = _roc_year_month(start)
    y1, m1 = _roc_year_month(end)
    return {
        "submission_date": sub,
        "submission_yyyymm": roc_yyyymm(sub),
        "submission_year_gregorian": str(sub.year),
        "attribution_year_start": y0,
        "attribution_month_start": m0,
        "attribution_year_end": y1,
        "attribution_month_end": m1,
    }


def period_to_structured_fields(period: Dict[str, Any]) -> Dict[str, str]:
    """寫入 llm_structured / 匯出用中文欄位名。"""
    return {
        "送件年月": str(period.get("submission_yyyymm") or ""),
        "所屬年(起)": str(period.get("attribution_year_start") or ""),
        "所屬月(起)": str(period.get("attribution_month_start") or ""),
        "所屬年(迄)": str(period.get("attribution_year_end") or ""),
        "所屬月(迄)": str(period.get("attribution_month_end") or ""),
    }


def submission_uploaded_at_iso(period: Dict[str, Any]) -> str:
    sub: date = period["submission_date"]
    return datetime(sub.year, sub.month, 1, 12, 0, 0).isoformat()


def parse_roc_year_month(roc_year: Any, roc_month: Any) -> date | None:
    """民國年 + 月 → 該月 1 日（進項憑證所屬期間用）。"""
    try:
        if roc_year is None or roc_month is None:
            return None
        if isinstance(roc_year, float) and roc_year != roc_year:
            return None
        if isinstance(roc_month, float) and roc_month != roc_month:
            return None
    except Exception:
        pass

    def _part(val: Any) -> int | None:
        if val is None:
            return None
        s = str(val).strip()
        if not s or s.lower() in ("nan", "none", "nat"):
            return None
        try:
            f = float(s.replace(",", ""))
            if f == int(f):
                return int(f)
        except (TypeError, ValueError):
            pass
        return int(s) if s.isdigit() else None

    y, m = _part(roc_year), _part(roc_month)
    if y is None or m is None or m < 1 or m > 12:
        return None
    try:
        return date(y + 1911, m, 1)
    except (TypeError, ValueError):
        return None


def attribution_bounds_from_voucher_row(row: Any) -> Tuple[Optional[date], Optional[date]]:
    """自進項憑證列讀取所屬(起)～所屬(迄)之月份區間。"""
    y0 = _row_get(row, ("attribution_year_start", "所屬年(起)"), default="")
    m0 = _row_get(row, ("attribution_month_start", "所屬月(起)"), default="")
    y1 = _row_get(row, ("attribution_year_end", "所屬年(迄)"), default="") or y0
    m1 = _row_get(row, ("attribution_month_end", "所屬月(迄)"), default="") or m0
    start = parse_roc_year_month(y0, m0)
    end = parse_roc_year_month(y1, m1)
    if start and end and end < start:
        end = start
    return start, end


def year_month_key(d: date) -> int:
    return int(d.year) * 12 + int(d.month)


def parse_roc_yyyymm(value: str) -> date | None:
    """解析民國 YYYMM（例 11505）為該月 1 日；失敗回傳 None。"""
    s = str(value or "").strip()
    if len(s) < 5 or not s.isdigit():
        return None
    try:
        roc_y = int(s[:-2])
        m = int(s[-2:])
        if m < 1 or m > 12:
            return None
        return date(roc_y + 1911, m, 1)
    except (TypeError, ValueError):
        return None


def _row_get(row: Any, keys: Tuple[str, ...], default: Any = "") -> Any:
    for k in keys:
        try:
            if hasattr(row, "index") and k in row.index:
                v = row[k]
            elif isinstance(row, dict) and k in row:
                v = row[k]
            else:
                continue
        except Exception:
            continue
        if v is None:
            continue
        if isinstance(v, float) and v != v:  # NaN
            continue
        if isinstance(v, str) and not v.strip():
            continue
        return v
    return default


def _parse_row_date(val: Any) -> Optional[date]:
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "nat"):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")[:26]).date()
    except ValueError:
        pass
    try:
        import pandas as pd

        ts = pd.to_datetime(val, errors="coerce")
        if ts is not None and not pd.isna(ts):
            return ts.date()
    except Exception:
        pass
    return None


def _roc_yyyymm_from_date(d: date) -> str:
    return roc_yyyymm(d)


def period_from_invoice_row(row: Any) -> Optional[Dict[str, Any]]:
    """
    由發票資料列推算送件／所屬期間（匯出、報表用）。
    優先順序：submission_yyyymm → uploaded_at（分析儲存時對應送件月）→ created_at。
    若列上僅有部分所屬欄位，仍以送件年月重算，避免起迄被誤設成同一月。
    """
    sub_roc = str(
        _row_get(
            row,
            (SUBMISSION_YYYYMM_DB_COLUMN, "submission_yyyymm", "送件年月"),
            default="",
        )
        or ""
    ).strip()
    if not sub_roc:
        for key in ("uploaded_at", "created_at"):
            d = _parse_row_date(_row_get(row, (key,), default=None))
            if d is not None:
                sub_roc = _roc_yyyymm_from_date(d)
                break
    sub_dt = parse_roc_yyyymm(sub_roc) if sub_roc else None
    if sub_dt is not None:
        return compute_submission_period(sub_dt)

    y0 = str(_row_get(row, ("attribution_year_start", "所屬年(起)"), default="") or "").strip()
    m0 = str(_row_get(row, ("attribution_month_start", "所屬月(起)"), default="") or "").strip()
    y1 = str(_row_get(row, ("attribution_year_end", "所屬年(迄)"), default="") or "").strip()
    m1 = str(_row_get(row, ("attribution_month_end", "所屬月(迄)"), default="") or "").strip()
    if y0 and m0 and y1 and m1:
        return {
            "submission_date": None,
            "submission_yyyymm": sub_roc,
            "submission_year_gregorian": "",
            "attribution_year_start": y0,
            "attribution_month_start": m0,
            "attribution_year_end": y1,
            "attribution_month_end": m1,
        }
    return None


def get_submission_period_from_session(state: Any, *, fallback_today: bool = True) -> Dict[str, Any]:
    """
    從 Streamlit session_state 讀取「送件年份／月份」widget，計算送件與所屬期間。
    分析、儲存、匯出應一律以此為準，而非系統當下時間。
    """
    try:
        roc_y = state.get("analyze_submission_roc_year")
        month = state.get("analyze_submission_month")
        if roc_y is not None and month is not None:
            return compute_submission_period(date(int(roc_y) + 1911, int(month), 1))
    except (TypeError, ValueError):
        pass
    cached = state.get("analyze_submission_period")
    if isinstance(cached, dict) and cached:
        return dict(cached)
    if fallback_today:
        return compute_submission_period(date.today().replace(day=1))
    raise ValueError("未設定送件月份")


# Supabase invoices 表欄位名（民國送件年月 YYYMM，例 11505）
SUBMISSION_YYYYMM_DB_COLUMN = "submission_yyymm"


def period_attribution_fields(period: Dict[str, Any]) -> Dict[str, Any]:
    """所屬年月起迄（匯出進項憑證、報表用；invoices 表通常不存這些欄位）。"""
    return {
        "attribution_year_start": period["attribution_year_start"],
        "attribution_month_start": period["attribution_month_start"],
        "attribution_year_end": period["attribution_year_end"],
        "attribution_month_end": period["attribution_month_end"],
    }


def period_row_fields(period: Dict[str, Any]) -> Dict[str, Any]:
    """寫入 Supabase invoices 的期間欄位（目前僅送件年月 submission_yyymm）。"""
    return {
        SUBMISSION_YYYYMM_DB_COLUMN: period["submission_yyyymm"],
    }

"""
進項憑證明細：依扣抵狀態分檔，寫入本機資料夾。

資料夾命名：{民國年}年{已扣抵|未扣抵}憑證({所屬起月}-{所屬迄月}月)
例：115年已扣抵憑證(01-02月)
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from utils.invoice_export import _parse_deductible_tri
from utils.submission_period import attribution_bounds_from_voucher_row, parse_roc_yyyymm

# accounting/exports
DEFAULT_EXPORT_ROOT = Path(__file__).resolve().parents[1] / "exports"


def export_root_path() -> Path:
    return DEFAULT_EXPORT_ROOT


def _deductible_mask(df: pd.DataFrame) -> pd.Series:
    """True=已扣抵(可扣抵)，False=未扣抵(不可扣抵)。"""
    if df is None or df.empty:
        return pd.Series(dtype=bool)

    def _row_flag(row: pd.Series) -> bool:
        if "扣抵否" in row.index:
            tri = _parse_deductible_tri(row["扣抵否"])
            if tri is True:
                return True
            if tri is False:
                return False
            s = str(row["扣抵否"] or "").strip().upper()
            if s == "Y":
                return True
            if s == "N":
                return False
        return False

    return df.apply(_row_flag, axis=1)


def split_by_deductible(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if df is None or df.empty:
        empty = pd.DataFrame()
        return empty, empty
    mask = _deductible_mask(df)
    return df.loc[mask].copy(), df.loc[~mask].copy()


def _roc_year_from_df(df: pd.DataFrame) -> str:
    years: List[str] = []
    if "送件年月" in df.columns:
        for v in df["送件年月"]:
            s = str(v or "").strip()
            if len(s) >= 5 and s[:3].isdigit():
                years.append(s[:3])
    if not years and "所屬年(起)" in df.columns:
        for v in df["所屬年(起)"]:
            s = str(v or "").strip()
            if s.isdigit():
                years.append(s.zfill(3)[-3:])
    if years:
        return Counter(years).most_common(1)[0][0]
    return "000"


def _attribution_month_range_label(df: pd.DataFrame) -> str:
    """所屬起迄月份，例：01-02月。"""
    months: List[int] = []
    if df is not None and not df.empty:
        for _, row in df.iterrows():
            start, end = attribution_bounds_from_voucher_row(row)
            if start:
                months.append(int(start.month))
            if end:
                months.append(int(end.month))
        if not months and "送件年月" in df.columns:
            for v in df["送件年月"]:
                d = parse_roc_yyyymm(str(v or ""))
                if d is not None:
                    months.append(int(d.month))
    if not months:
        return "01-12月"
    lo, hi = min(months), max(months)
    if lo == hi:
        return f"{lo:02d}-{hi:02d}月"
    return f"{lo:02d}-{hi:02d}月"


def build_folder_name(
    df: pd.DataFrame,
    *,
    deductible: bool,
    roc_year: Optional[str] = None,
    month_range: Optional[str] = None,
) -> str:
    ry = (roc_year or _roc_year_from_df(df)).strip()
    mr = (month_range or _attribution_month_range_label(df)).strip()
    kind = "已扣抵" if deductible else "未扣抵"
    return f"{ry}年{kind}憑證({mr})"


def _write_excel(path: Path, df: pd.DataFrame, sheet_name: str = "進項憑證明細") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])


def export_vouchers_to_folders(
    df: pd.DataFrame,
    *,
    export_root: Optional[Path] = None,
    column_order: Optional[List[str]] = None,
    archive_df: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """
    將資料依扣抵拆成兩份 Excel，各存入對應名稱資料夾。
    回傳 dirs、files、counts、skipped_empty。
    """
    root = Path(export_root or DEFAULT_EXPORT_ROOT)
    result: Dict[str, Any] = {
        "root": str(root.resolve()),
        "dirs": [],
        "files": [],
        "counts": {"deductible": 0, "non_deductible": 0},
        "folder_names": [],
        "errors": [],
    }
    if df is None or df.empty:
        result["errors"].append("沒有資料可匯出。")
        return result

    cols = column_order
    if cols:
        use_cols = [c for c in cols if c in df.columns]
        base = df[use_cols].copy() if use_cols else df.copy()
    else:
        base = df.copy()

    df_yes, df_no = split_by_deductible(base)
    roc_year = _roc_year_from_df(base)
    month_range = _attribution_month_range_label(base)

    archive_source = (
        archive_df
        if archive_df is not None and not archive_df.empty
        else base
    )
    arch_yes, arch_no = split_by_deductible(archive_source)

    from utils.invoice_file_archive import (
        _empty_archive_result,
        _merge_archive_results,
        archive_import_files_to_folder,
    )

    combined_archive = _empty_archive_result()

    specs = [
        (True, df_yes, arch_yes, "deductible"),
        (False, df_no, arch_no, "non_deductible"),
    ]
    for deductible, part, arch_part, key in specs:
        result["counts"][key] = int(len(part))
        if part.empty:
            continue
        folder_name = build_folder_name(
            part,
            deductible=deductible,
            roc_year=roc_year,
            month_range=month_range,
        )
        folder = root / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        xlsx_path = folder / f"{folder_name}.xlsx"
        try:
            _write_excel(xlsx_path, part)
        except Exception as e:
            result["errors"].append(f"「{folder_name}」寫入失敗：{e}")
            continue
        result["dirs"].append(str(folder.resolve()))
        result["files"].append(str(xlsx_path.resolve()))
        result["folder_names"].append(folder_name)

        if arch_part is not None and not arch_part.empty:
            part_archive = archive_import_files_to_folder(arch_part, folder)
            _merge_archive_results(combined_archive, part_archive)

    if not result["files"] and not result["errors"]:
        result["errors"].append("扣抵欄位無法分類或無有效列可匯出。")

    if (
        combined_archive.get("moved")
        or combined_archive.get("not_found")
        or combined_archive.get("errors")
    ):
        result["archive"] = combined_archive
        result["moved_files"] = list(combined_archive.get("moved") or [])

    return result

"""
進項憑證發票檔案：import 待歸檔 → exports 依扣抵／所屬月份資料夾。

import 內檔名須與資料庫「進項憑證明細」的 uuid／檔名欄位相同（不含副檔名）。
例：資料庫 uuid = b677bf56-... → import/b677bf56-....jpg
"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from utils.invoice_export import _parse_deductible_tri
from utils.voucher_file_export import (
    DEFAULT_EXPORT_ROOT,
    build_folder_name,
)

DEFAULT_IMPORT_ROOT = Path(__file__).resolve().parents[1] / "import"

INVOICE_FILE_SUFFIXES = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tif",
    ".tiff",
    ".heic",
    ".bmp",
}

# 資料庫可能使用的檔名欄位（優先順序）
FILE_KEY_COLUMN_CANDIDATES = (
    "uuid",
    "檔名",
    "發票檔案",
    "檔案名稱",
    "file_name",
    "filename",
    "invoice_file",
)


def import_root_path() -> Path:
    return DEFAULT_IMPORT_ROOT


def normalize_file_key(val: Any) -> str:
    """將資料庫檔名／uuid 轉成與 import 檔案 stem 比對用的字串。"""
    s = str(val or "").strip()
    if not s or s.lower() in ("nan", "none", "nat"):
        return ""
    s = s.replace("\\", "/")
    if "/" in s:
        s = s.rsplit("/", 1)[-1]
    p = Path(s)
    if p.suffix and len(p.suffix) <= 6:
        s = p.stem
    return str(s).strip()


def normalize_uuid(val: Any) -> str:
    return normalize_file_key(val)


def file_key_column(df: pd.DataFrame) -> Optional[str]:
    if df is None or df.empty:
        return None
    lower_map = {str(c).strip().lower(): str(c) for c in df.columns}
    for want in FILE_KEY_COLUMN_CANDIDATES:
        key = want.lower()
        if key in lower_map:
            return lower_map[key]
    return None


def _uuid_column(df: pd.DataFrame) -> Optional[str]:
    return file_key_column(df)


def _row_is_deductible(row: pd.Series) -> bool:
    if "扣抵否" not in row.index:
        return False
    tri = _parse_deductible_tri(row["扣抵否"])
    if tri is True:
        return True
    if tri is False:
        return False
    s = str(row["扣抵否"] or "").strip().upper()
    return s == "Y"


def file_keys_from_row(row: pd.Series) -> List[str]:
    """從列上所有可能的檔名欄位收集比對用關鍵字（去重）。"""
    keys: List[str] = []
    seen: set[str] = set()
    for want in FILE_KEY_COLUMN_CANDIDATES:
        for col in row.index:
            if str(col).strip().lower() != want.lower():
                continue
            k = normalize_file_key(row.get(col))
            if k and k.lower() not in seen:
                seen.add(k.lower())
                keys.append(k)
            break
    return keys


_import_index_cache: Optional[Dict[str, List[Path]]] = None


def _invalidate_import_index() -> None:
    global _import_index_cache
    _import_index_cache = None


def _build_import_index() -> Dict[str, List[Path]]:
    global _import_index_cache
    if _import_index_cache is not None:
        return _import_index_cache
    idx: Dict[str, List[Path]] = {}
    root = import_root_path()
    if not root.is_dir():
        _import_index_cache = idx
        return idx
    for p in root.iterdir():
        if not p.is_file() or p.name.startswith("."):
            continue
        if p.suffix and p.suffix.lower() not in INVOICE_FILE_SUFFIXES:
            continue
        key = p.stem.lower()
        idx.setdefault(key, []).append(p)
    for paths in idx.values():
        paths.sort(key=lambda x: x.name.lower())
    _import_index_cache = idx
    return idx


def list_import_file_keys() -> List[str]:
    return sorted(_build_import_index().keys())


def find_import_files(file_key: str) -> List[Path]:
    k = normalize_file_key(file_key)
    if not k:
        return []
    return list(_build_import_index().get(k.lower(), []))


def find_import_files_for_row(row: pd.Series) -> List[Path]:
    for key in file_keys_from_row(row):
        found = find_import_files(key)
        if found:
            return found
    return []


def destination_dir_for_row(
    row: pd.Series,
    *,
    export_root: Optional[Path] = None,
) -> Path:
    root = Path(export_root or DEFAULT_EXPORT_ROOT)
    part = pd.DataFrame([row])
    folder_name = build_folder_name(part, deductible=_row_is_deductible(row))
    return root / folder_name


def _safe_move(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    target = dest
    if target.exists():
        stem, suf = target.stem, target.suffix
        n = 1
        while target.exists():
            target = target.parent / f"{stem}_{n}{suf}"
            n += 1
    try:
        shutil.move(str(src), str(target))
    except OSError:
        shutil.copy2(str(src), str(target))
        try:
            src.unlink()
        except OSError:
            pass
    _invalidate_import_index()
    return target


def move_import_files_for_row(
    row: Union[pd.Series, Dict[str, Any]],
    *,
    export_root: Optional[Path] = None,
    dest_dir: Optional[Path] = None,
) -> List[str]:
    """依資料庫檔名欄位，將 import 內同名檔案移至目標資料夾（預設為 exports 子資料夾）。"""
    if isinstance(row, dict):
        row = pd.Series(row)
    keys = file_keys_from_row(row)
    if not keys:
        return []
    target_dir = Path(dest_dir) if dest_dir is not None else destination_dir_for_row(
        row, export_root=export_root
    )
    moved: List[str] = []
    seen_src: set[str] = set()
    for src in find_import_files_for_row(row):
        if not src.is_file():
            continue
        sk = str(src.resolve())
        if sk in seen_src:
            continue
        seen_src.add(sk)
        dest = _safe_move(src, target_dir / src.name)
        moved.append(str(dest.resolve()))
    return moved


def _empty_archive_result() -> Dict[str, Any]:
    return {
        "moved": [],
        "not_found": [],
        "missing_file_key": 0,
        "import_file_count": len(list_import_file_keys()),
        "file_key_column": None,
        "errors": [],
    }


def _merge_archive_results(acc: Dict[str, Any], part: Dict[str, Any]) -> None:
    acc["moved"].extend(part.get("moved") or [])
    acc["not_found"].extend(part.get("not_found") or [])
    acc["missing_file_key"] += int(part.get("missing_file_key") or 0)
    if part.get("file_key_column") and not acc.get("file_key_column"):
        acc["file_key_column"] = part["file_key_column"]
    acc["errors"].extend(part.get("errors") or [])


def archive_import_files_to_folder(
    df: pd.DataFrame,
    folder: Path,
) -> Dict[str, Any]:
    """將 import 內與資料列檔名相符的發票檔移入指定資料夾（與 Excel 同目錄）。"""
    result = _empty_archive_result()
    if df is None or df.empty:
        return result

    col = file_key_column(df)
    result["file_key_column"] = col
    if not col:
        result["errors"].append(
            "資料中無 uuid／檔名欄位，無法對應 import 檔案。"
            f"（支援欄位：{', '.join(FILE_KEY_COLUMN_CANDIDATES)}）"
        )
        return result

    dest = Path(folder)
    dest.mkdir(parents=True, exist_ok=True)
    _build_import_index()

    for _, row in df.iterrows():
        keys = file_keys_from_row(row)
        if not keys:
            result["missing_file_key"] += 1
            continue
        paths = move_import_files_for_row(row, dest_dir=dest)
        if paths:
            result["moved"].extend(paths)
        else:
            result["not_found"].append(keys[0])
    result["import_file_count"] = len(list_import_file_keys())
    return result


def archive_import_files_for_dataframe(
    df: pd.DataFrame,
    *,
    export_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    依資料庫 uuid／檔名欄位，將 import 內同名檔案移至 exports 子資料夾。
    不依賴發票分析 session；僅比對資料庫欄位與 import 檔名。
    """
    if df is None or df.empty:
        return _empty_archive_result()

    result = _empty_archive_result()
    col = file_key_column(df)
    result["file_key_column"] = col
    if not col:
        result["errors"].append(
            "資料中無 uuid／檔名欄位，無法對應 import 檔案。"
            f"（支援欄位：{', '.join(FILE_KEY_COLUMN_CANDIDATES)}）"
        )
        return result

    _build_import_index()
    for _, row in df.iterrows():
        keys = file_keys_from_row(row)
        if not keys:
            result["missing_file_key"] += 1
            continue
        paths = move_import_files_for_row(row, export_root=export_root)
        if paths:
            result["moved"].extend(paths)
        else:
            result["not_found"].append(keys[0])
    result["import_file_count"] = len(list_import_file_keys())
    return result


def save_bytes_to_import(file_uuid: str, data: bytes, ext: str = "jpg") -> Optional[Path]:
    """將發票影像寫入 import/{檔名}.{ext}（選用，供發票分析）。"""
    uid = normalize_file_key(file_uuid)
    if not uid or not data:
        return None
    ext_clean = str(ext or "jpg").strip().lstrip(".").lower() or "jpg"
    root = import_root_path()
    root.mkdir(parents=True, exist_ok=True)
    dest = root / f"{uid}.{ext_clean}"
    dest.write_bytes(data)
    return dest


def ensure_uuids_on_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """僅在缺檔名時產生 uuid（上傳新資料用）；歸檔時請勿呼叫。"""
    if df is None or df.empty:
        return df
    out = df.copy()
    col = file_key_column(out)
    if col is None:
        out["uuid"] = ""
        col = "uuid"
    for idx in out.index:
        if not normalize_file_key(out.at[idx, col]):
            out.at[idx, col] = str(uuid.uuid4())
    return out


def register_analysis_file_to_import(analysis: Dict[str, Any]) -> str:
    """發票分析完成後寫入 import（選用）。"""
    uid = normalize_file_key(analysis.get("uuid"))
    if not uid:
        uid = str(uuid.uuid4())
    analysis["uuid"] = uid
    data = analysis.get("_file_bytes")
    if data:
        ext = str(analysis.get("_file_ext") or "jpg").lstrip(".") or "jpg"
        save_bytes_to_import(uid, data, ext)
    return uid

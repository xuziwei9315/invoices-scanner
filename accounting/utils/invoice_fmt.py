"""發票欄位顯示／儲存用格式處理。"""


def normalize_invoice_number(value: object) -> str:
    """
    發票號碼不保留中間的連字號（含半形 -、全形 －、長破折號 —）。
    台灣統一發票格式為 2 英字 + 8 數字，僅去除分隔符，不做其他推斷。
    """
    s = str(value or "").strip()
    if not s:
        return ""
    for ch in ("-", "－", "—", "–"):
        s = s.replace(ch, "")
    return s.strip()


def normalize_buyer_tax_id(value: object) -> str:
    """
    買方統編（營利事業統一編號）：去除空白與連字號後僅保留數字，最多 8 碼。
    """
    s = str(value or "").strip()
    for ch in ("-", "－", "—", "–", " ", "\u3000"):
        s = s.replace(ch, "")
    digits = "".join(c for c in s if c.isdigit())
    return digits[:8] if digits else ""

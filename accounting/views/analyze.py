import math
import streamlit as st
import pandas as pd
import random
import os
import base64
import re
import google.generativeai as genai
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List  # 補上類型宣告
from utils.layout import header, card
from utils.database import insert_invoice_to_supabase
from utils.app_refresh import refresh_invoice_caches
from utils.prefs import load_llm_api_keys, load_llm_model_for, save_llm_model_for
from utils.llm_models import fetch_anthropic_model_ids, fetch_openai_model_ids
from utils.invoice_fmt import normalize_invoice_number, normalize_buyer_tax_id
from utils.account_chart import (
    get_chart_rows,
    chart_names_sorted,
    best_match_account_name,
    get_account_chart_status,
)
from utils.submission_period import (
    compute_submission_period,
    get_submission_period_from_session,
    period_from_invoice_row,
    period_row_fields,
    period_to_structured_fields,
    submission_uploaded_at_iso,
)
from utils.user_tax import login_user_name
from utils.invoice_file_archive import register_analysis_file_to_import

# 專案根目錄（用於暫存檔）
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# 系統預設 Prompt（當使用者未在「系統設定」設定個人預設 Prompt 時，使用此 fallback）
DEFAULT_ANALYZE_PROMPT = "請辨識發票並判斷扣抵性..."

try:
    from services.llm_service import LlmService  # type: ignore
except Exception:
    # 不在 import 時就炸掉整個頁面；按下分析時會給出錯誤訊息
    LlmService = None  # type: ignore

try:
    import fitz  # type: ignore[import-not-found]  # PyMuPDF
except Exception:
    fitz = None  # type: ignore

# ── 內部輔助函式 (原本在主檔案的邏輯) ──────────────────────────────────────────

def _buyer_tax_id_for_row(inv0: Dict[str, Any], raw_structured: Any) -> str:
    """
    寫入 DB 的 buyer_tax_id（買方統編）。
    優先：畫面／invoice 的買方統編 → LLM 擷取 → 登入使用者 users.buyer_tax_id／tax_id／org_tax_id。
    """
    user = st.session_state.get("user") or {}
    tid = normalize_buyer_tax_id(inv0.get("買方統編", ""))
    if not tid and isinstance(raw_structured, dict):
        tid = normalize_buyer_tax_id(raw_structured.get("買方統編", ""))
    if not tid:
        tid = normalize_buyer_tax_id(
            user.get("buyer_tax_id") or user.get("tax_id") or user.get("org_tax_id") or ""
        )
    return tid


def mock_history_cases() -> List[Dict[str, str]]:
    return [
        {"案例": "2026-03 雲端訂閱", "結論": "可扣抵",  "理由": "屬營業使用之雲端服務費用。"},
        {"案例": "2026-02 交際餐飲", "結論": "不可扣抵", "理由": "疑似交際應酬性質。"},
    ]

def _apply_prompt_deductibility_with_gemini(analysis: Dict[str, Any], user_prompt: str, temperature: float) -> None:
    """
    以「發票分析」頁面的 Prompt 為準，用 Gemini（若已設定 Google API key）補上可扣抵與規則/理由。
    用於 OpenAI／Anthropic mock 擷取時仍可套用同一套準則判斷。
    """
    if LlmService is None:
        return
    keys = st.session_state.get("llm_api_keys") or {}
    api_key = str(keys.get("google") or "").strip()
    if not api_key:
        return
    inv = analysis.get("invoice")
    if not isinstance(inv, dict):
        return
    model_name = str(st.session_state.get("google_model_name") or "").strip() or None
    try:
        svc = LlmService(api_key=api_key, model_name=model_name)
        jd = svc.evaluate_deductibility(user_prompt, inv, temperature=float(temperature))
    except Exception:
        return
    if not jd:
        return
    analysis.setdefault("ai", {})
    analysis["ai"]["可扣抵"] = bool(jd.get("可扣抵"))
    try:
        cf = float(jd.get("信心", 0.7))
    except Exception:
        cf = 0.7
    analysis["ai"]["信心"] = max(0.0, min(1.0, cf))

    exp = analysis.setdefault("explain", {})
    r0 = str(jd.get("原因") or exp.get("原因", "") or "").strip()
    if r0:
        exp["原因"] = r0
    rules_in = jd.get("規則") if isinstance(jd.get("規則"), list) else []
    base_rules = [{"項目": "欄位擷取（mock）", "結果": "通過"}]
    exp["規則"] = base_rules + list(rules_in)
    exp.setdefault("歷史案例", mock_history_cases())


def _apply_submission_period_to_analysis(a: Dict[str, Any], period: Dict[str, Any]) -> None:
    """將送件／所屬期間寫入 analysis 與 llm_structured。"""
    a["submission_period"] = dict(period)
    fields = period_to_structured_fields(period)
    raw = a.get("llm_structured")
    if not isinstance(raw, dict):
        raw = {}
        a["llm_structured"] = raw
    raw.update(fields)


def _period_pill_html(label: str, value: str, *, variant: str = "neutral") -> str:
    """variant: neutral | primary | accent"""
    cls = "period-pill"
    if variant == "accent":
        cls += " period-pill-accent"
    elif variant == "primary":
        cls += " period-pill-primary"
    return (
        f"<div class='{cls}'>"
        f"<span class='label'>{label}</span>"
        f"<span class='value'>{value}</span>"
        f"</div>"
    )


def _render_submission_month_selector() -> Dict[str, Any]:
    """輸入區／結果區上方：全寬橫向送件月份與所屬期間長條。"""
    today = date.today()
    default_roc_y = today.year - 1911
    roc_years = list(range(default_roc_y - 8, default_roc_y + 3))

    st.markdown(
        """
        <div class="submission-period-section">
          <div class="submission-period-head">
            <div class="submission-period-head-title">送件月份</div>
            <div class="submission-period-head-hint">所屬(起)＝送件月往前 2 個月 · 所屬(迄)＝往前 1 個月 · 分析時自動帶入</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with card():
        st.markdown('<div class="submission-period-bar-marker"></div>', unsafe_allow_html=True)

        c_pick, c_arrow, c_out = st.columns(
            [1.15, 0.14, 2.35],
            gap="small",
            vertical_alignment="center",
        )

        with c_pick:
            st.markdown("<div class='submission-zone-label'>選擇送件期間</div>", unsafe_allow_html=True)
            c_y, c_m = st.columns(2, gap="small")
            with c_y:
                roc_y = st.selectbox(
                    "民國年",
                    options=roc_years,
                    index=roc_years.index(default_roc_y) if default_roc_y in roc_years else len(roc_years) - 1,
                    key="analyze_submission_roc_year",
                    format_func=lambda y: f"{y} 年",
                )
            with c_m:
                month = st.selectbox(
                    "月份",
                    options=list(range(1, 13)),
                    index=today.month - 1,
                    key="analyze_submission_month",
                    format_func=lambda m: f"{m:02d} 月",
                )

        with c_arrow:
            st.markdown(
                "<div class='submission-period-arrow' aria-hidden='true'>→</div>",
                unsafe_allow_html=True,
            )

        period = compute_submission_period(date(int(roc_y) + 1911, int(month), 1))
        st.session_state["analyze_submission_period"] = period

        with c_out:
            st.markdown("<div class='submission-zone-label'>帶入分析與匯出</div>", unsafe_allow_html=True)
            c_sub, c_start, c_end = st.columns(3, gap="small")
            with c_sub:
                st.markdown(
                    _period_pill_html("送件年月", period["submission_yyyymm"], variant="primary"),
                    unsafe_allow_html=True,
                )
            with c_start:
                st.markdown(
                    _period_pill_html(
                        "所屬(起)",
                        f"{period['attribution_year_start']} 年 {period['attribution_month_start']} 月",
                        variant="accent",
                    ),
                    unsafe_allow_html=True,
                )
            with c_end:
                st.markdown(
                    _period_pill_html(
                        "所屬(迄)",
                        f"{period['attribution_year_end']} 年 {period['attribution_month_end']} 月",
                        variant="accent",
                    ),
                    unsafe_allow_html=True,
                )
    return period


def _period_for_save(a: Any = None) -> Dict[str, Any]:
    if a and a.get("submission_period"):
        return a["submission_period"]
    return get_submission_period_from_session(st.session_state)


def _refresh_analyze_page_after_save(message: str, sb: Any = None) -> None:
    """結果區儲存成功後：更新快取、提示訊息並重跑頁面以刷新結果區。"""
    st.session_state["analyze_save_flash"] = str(message or "已儲存。")
    st.session_state["analyze_ui_rev"] = int(st.session_state.get("analyze_ui_rev", 0) or 0) + 1
    refresh_invoice_caches(sb)
    st.rerun()


def _invoice_db_fields_from_period(period: Dict[str, Any]) -> Dict[str, Any]:
    """寫入 invoices 的送件年月與所屬期間（來自分析頁使用者選擇）。"""
    return period_row_fields(period)


def _invoice_uploader_field() -> Dict[str, str]:
    """寫入 invoices.user_name：目前登入者帳號。"""
    name = login_user_name()
    return {"user_name": name} if name else {}


def run_mock_analysis(
    llm: str, prompt: str, file_size: int, model_id: str = "", *, seq: int = 0
) -> Dict[str, Any]:
    rng       = random.Random(1000 + file_size + int(seq) * 97)
    inv_seq   = (file_size + int(seq) * 17) % 9_999_999
    inv_no    = f"AB{inv_seq:07d}"
    inv_date  = (date.today() - timedelta(days=rng.randint(0, 20))).isoformat()
    amount    = _truncate_amount(1500 + (file_size % 24000) * 0.9)
    tax       = _truncate_amount(amount * 0.05)
    total     = _truncate_amount(amount + tax)
    deductible = (file_size % 2) == 0
    conf       = round(0.78 + (file_size % 18) / 100, 2)
    
    llm_label = f"{llm} · {model_id.strip()}" if str(model_id or "").strip() else llm
    return {
        "llm":    llm_label,
        "prompt": prompt,
        "invoice": {
            "發票號碼": inv_no,
            "發票類型": "",
            "會計科目": "",
            "交易日期": inv_date,
            "應稅金額":  amount,
            "稅額":      tax,
            "含稅金額":  total,
            "買方統編": "",
            "賣方統編": str(rng.randint(10_000_000, 99_999_999)),
            "賣方名稱": "（本次上傳）",
            "品名/備註": "—",
            "狀態": "已辨識（mock）",
        },
        "ai": {
            "可扣抵": deductible,
            "信心":   conf,
        },
        "explain": {
            "原因": "格式欄位完整，且用途符合條件。" if deductible else "需人工覆核用途。",
            "規則": [
                {"項目": "發票格式檢查",   "結果": "通過"},
                {"項目": "用途/類別匹配",  "結果": "通過" if deductible else "需覆核"},
            ],
            "歷史案例": mock_history_cases(),
        },
    }


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(str(v).replace(",", "").strip())
    except Exception:
        return default


def _truncate_amount(v: Any, default: float = 0.0) -> float:
    """金額無條件捨去小數（朝零方向截斷）。"""
    return float(math.trunc(_safe_float(v, default)))


def _truncate_invoice_amounts(inv: Dict[str, Any]) -> Dict[str, Any]:
    """將發票明細的應稅金額、稅額、含稅金額無條件捨去小數。"""
    out = dict(inv or {})
    for key in ("應稅金額", "稅額", "含稅金額"):
        out[key] = _truncate_amount(out.get(key), 0.0)
    return out


def _is_deductible_from_analysis(a: Dict[str, Any]) -> bool:
    """從發票分析結果 `ai.可扣抵` 讀取，供寫入資料庫 `is_deductible`。"""
    ai = a.get("ai") if isinstance(a.get("ai"), dict) else {}
    return bool(ai.get("可扣抵", False))


def _image_viewport(file_bytes: bytes, ext: str, caption: str, zoom: float, vw: int = 420, vh: int = 520) -> None:
    """
    固定寬高的可捲動視窗，圖片尺寸可隨 zoom 調整（會觸發水平/垂直捲動）。
    """
    e = (ext or "").lower()
    mime = "image/jpeg" if e in ("jpg", "jpeg") else ("image/png" if e == "png" else ("image/webp" if e == "webp" else "image/jpeg"))
    data_url = f"data:{mime};base64,{base64.b64encode(file_bytes).decode('ascii')}"
    img_w = int(360 * float(zoom))
    # 以 HTML 方式渲染，確保 viewport 寬高固定 + 可雙向捲動
    st.markdown(
        f"""
        <div style="width:{vw}px;height:{vh}px;overflow:auto;border:1px solid rgba(0,0,0,0.12);border-radius:10px;padding:8px;background:rgba(255,255,255,0.65);">
          <div style="font-size:12px;opacity:0.8;margin-bottom:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{caption}</div>
          <img src="{data_url}" style="width:{img_w}px;max-width:none;display:block;border-radius:8px;" />
        </div>
        """,
        unsafe_allow_html=True,
    )


def _safe_filename(s: str) -> str:
    s0 = (s or "").strip()
    if not s0:
        return "file"
    s0 = re.sub(r"[^\w\-.]+", "_", s0, flags=re.UNICODE)
    return s0[:120] or "file"


def _pdf_to_page_images(pdf_path: str, out_dir: str, max_pages: int = 0) -> List[str]:
    """
    將 PDF 轉成逐頁 PNG 圖片並回傳路徑清單。
    - 使用 PyMuPDF（fitz），Windows 不需額外安裝 poppler。
    - 預設最多轉前 10 頁，避免一次性把超大 PDF 撐爆記憶體/時間。
    """
    if fitz is None:
        raise RuntimeError("尚未安裝 PyMuPDF（pymupdf），無法處理 PDF。請先安裝後再重啟。")

    doc = fitz.open(pdf_path)
    total_pages = int(doc.page_count or 0)
    max_pages_i = int(max_pages or 0)
    # max_pages=0 → 全部頁面
    n = total_pages if max_pages_i <= 0 else min(total_pages, max_pages_i)
    out: List[str] = []
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    base = _safe_filename(base)

    # 2x 放大，OCR/視覺辨識較穩（檔案仍可控）
    mat = fitz.Matrix(2, 2)
    for i in range(n):
        page = doc.load_page(i)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_path = os.path.join(out_dir, f"{base}_p{i+1}.png")
        pix.save(img_path)
        out.append(img_path)
    doc.close()
    return out


def run_gemini_extraction_from_image_path(
    prompt: str,
    image_path: str,
    file_name: str = "",
    temperature: float = 0.1,
    submission_period: Any = None,
) -> Dict[str, Any]:
    """
    直接用圖片路徑走 LlmService.structure_data()，並轉成本頁 UI 既有的 analysis 結構。
    用於支援 PDF 逐頁轉圖後的處理。
    """
    if LlmService is None:
        raise RuntimeError("無法載入 LlmService（請確認專案結構與依賴是否完整）")

    # 從 user_prefs.json（透過 session_state）取得 Google key，避免依賴 .env
    api_key = str(st.session_state.get("llm_api_key") or "").strip()
    model_name = str(st.session_state.get("google_model_name") or "").strip() or None
    svc = LlmService(api_key=api_key, model_name=model_name)
    sub_yyyymm = str((submission_period or {}).get("submission_yyyymm") or "").strip() or None
    structured = svc.structure_data(
        image_path,
        file_name=file_name,
        temperature=float(temperature),
        submission_yyyymm=sub_yyyymm,
    )

    has_err = bool(structured.get("__error"))
    status = "已辨識（Gemini）" if not has_err else "辨識失敗（Gemini）"

    def _normalize_invoice_type(v: Any) -> str:
        s = str(v or "").strip()
        if not s:
            return ""
        s0 = s.replace(" ", "")
        if "電子發票" in s0:
            return "電子發票"
        # 最具體：三聯式收銀機統一發票扣抵聯（優先於泛用「三聯」判斷）
        if ("收銀機" in s0) and ("三聯" in s0) and (("扣抵聯" in s0) or ("副聯式扣抵聯" in s0) or ("扣抵" in s0)):
            return "三聯式收銀機統一發票扣抵聯"
        # 再判斷三聯（含「收銀機三聯...」但非扣抵聯字樣的描述）
        if "三聯" in s0:
            return "三聯式統一發票"
        # 只要提到收銀機，但沒明確三聯，就歸類為二聯收銀機
        if "收銀機" in s0:
            return "二聯式收銀機統一發票"
        # 若出現「統一發票」但無法判斷，先回傳空字串讓使用者可手動選
        return ""

    # 金額：優先用「總計」，若缺漏則用「應稅金額 + 稅額」補推（皆無條件捨去小數）
    inv_total = _truncate_amount(structured.get("總計"), 0.0)
    if not inv_total:
        inv_total = _truncate_amount(
            _safe_float(structured.get("應稅金額"), 0.0) + _safe_float(structured.get("稅額"), 0.0)
        )
    inv_taxable = _truncate_amount(structured.get("應稅金額"), 0.0)
    inv_tax = _truncate_amount(structured.get("稅額"), 0.0)
    if (not inv_taxable) and inv_total:
        inv_taxable = _truncate_amount(inv_total / 1.05)
    if (not inv_tax) and inv_total:
        inv_tax = _truncate_amount(inv_total - inv_taxable)

    # 發票類型：優先用上游欄位；若缺漏則用 llm_service 產生的「發票種類」做對照分類
    invoice_type_auto = (
        structured.get("發票類型")
        or structured.get("invoice_type")
        or structured.get("發票種類")
    )
    invoice_type_auto = _normalize_invoice_type(invoice_type_auto)

    # 會計科目：由 AI（LLM service）直接產出
    account_auto = (
        structured.get("會計科目")
        or structured.get("會計科目代碼")
        or structured.get("account")
        or ""
    )
    account_auto = str(account_auto or "").strip()
    desc_for_acct = str(
        structured.get("科目摘要") or structured.get("品名") or structured.get("品名/備註") or ""
    ).strip()
    _chart = get_chart_rows()
    account_auto = best_match_account_name(account_auto, _chart, desc=desc_for_acct)

    inv = {
        "發票號碼": normalize_invoice_number(structured.get("發票號碼", "")),
        "發票類型": invoice_type_auto,
        "會計科目": account_auto,
        "交易日期": structured.get("交易日期", ""),
        "應稅金額": inv_taxable,
        "稅額": inv_tax,
        "含稅金額": inv_total,
        "賣方統編": structured.get("賣方統編", ""),
        "賣方名稱": structured.get("賣方公司名稱", ""),
        "買方統編": normalize_buyer_tax_id(structured.get("買方統編", "")),
        "品名/備註": structured.get("科目摘要", ""),
        "狀態": status,
    }

    jd: Dict[str, Any] = {}
    if (not has_err) and api_key:
        try:
            inv_for_judge = dict(inv)
            inv_for_judge["發票種類_raw"] = str(structured.get("發票種類", "") or "")
            jd = svc.evaluate_deductibility(prompt, inv_for_judge, temperature=float(temperature))
        except Exception:
            jd = {}

    if jd:
        try:
            cf = float(jd.get("信心", 0.7))
        except Exception:
            cf = 0.7
        ai = {"可扣抵": bool(jd.get("可扣抵")), "信心": max(0.0, min(1.0, cf))}
        rules_in = jd.get("規則") if isinstance(jd.get("規則"), list) else []
        explain = {
            "原因": str(jd.get("原因") or "已依「發票分析」頁面之 Prompt 完成扣抵判斷。").strip(),
            "規則": [{"項目": "欄位擷取", "結果": "通過"}] + list(rules_in),
            "歷史案例": mock_history_cases(),
        }
    else:
        ai = {"可扣抵": False, "信心": 0.5 if not has_err else 0.2}
        explain = {
            "原因": (
                "欄位擷取成功，但未能完成依 Prompt 之扣抵判斷（可稍後重試或檢查模型回覆）。"
                if not has_err
                else "欄位擷取失敗，請查看錯誤訊息。"
            ),
            "規則": [{"項目": "欄位擷取", "結果": "通過" if not has_err else "失敗"}],
            "歷史案例": mock_history_cases(),
        }
    if has_err:
        explain["錯誤"] = structured.get("__error", "")

    model_label = (model_name or getattr(svc, "model_name", "") or "").replace("models/", "")
    result = {
        "llm": f"Google · {model_label or 'gemini'}",
        "prompt": prompt,
        "invoice": inv,
        "ai": ai,
        "explain": explain,
        "llm_structured": structured,
        "_file_name": file_name or os.path.basename(image_path),
        "_file_ext": os.path.splitext(image_path)[1].lower().lstrip("."),
        "_file_bytes": open(image_path, "rb").read(),
    }
    _apply_submission_period_to_analysis(
        result,
        submission_period or get_submission_period_from_session(st.session_state),
    )
    return result


def run_gemini_extraction(
    prompt: str,
    uploaded_file,
    temperature: float = 0.1,
    submission_period: Any = None,
) -> Dict[str, Any]:
    """
    使用 accounting/services/llm_service.py 的 LlmService.structure_data() 進行發票欄位擷取，
    並轉成本頁 UI 既有的 analysis 結構。
    """
    if uploaded_file is None:
        raise RuntimeError("未上傳檔案")

    if LlmService is None:
        raise RuntimeError("無法載入 LlmService（請確認專案結構與依賴是否完整）")

    name = getattr(uploaded_file, "name", "") or "uploaded"
    ext = os.path.splitext(name)[1].lower().lstrip(".")
    if ext not in ("png", "jpg", "jpeg", "webp"):
        raise RuntimeError("目前 Gemini 擷取僅支援圖片（png/jpg/jpeg/webp）。")

    file_bytes = uploaded_file.getvalue()
    temp_dir = os.path.join(_ROOT, "temp")
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, name)
    with open(temp_path, "wb") as f:
        f.write(file_bytes)

    # 走共用路徑版（便於 PDF 轉圖後也復用同一段邏輯）
    return run_gemini_extraction_from_image_path(
        prompt=prompt,
        image_path=temp_path,
        file_name=name,
        temperature=float(temperature),
        submission_period=submission_period,
    )


def _short_model_name(full: str) -> str:
    s = str(full or "").strip()
    if not s:
        return ""
    return s.replace("models/", "")


def _ensure_google_model_pref() -> None:
    """
    初始化 Google 模型偏好：
    - 優先使用 user_prefs.json（users 專屬）
    - 其次使用環境變數 GEMINI_MODEL
    - 最後使用 LlmService 的預設
    """
    if st.session_state.get("google_model_name"):
        return
    user = st.session_state.get("user") or {}
    saved = load_llm_model_for(user, "google") if user else None
    if saved:
        st.session_state["google_model_name"] = str(saved)
        return
    env_v = str(os.getenv("GEMINI_MODEL") or "").strip()
    if env_v:
        st.session_state["google_model_name"] = env_v
        return
    st.session_state["google_model_name"] = "models/gemini-3-flash-preview"


def _refresh_google_models() -> None:
    """
    取得可用 Gemini 模型清單（過濾支援 generateContent）。
    需要使用者已在「系統設定 → LLM API Keys」保存 Google key。
    """
    if LlmService is None:
        st.session_state["google_models_cache"] = []
        st.session_state["google_models_error"] = "無法載入 LlmService。"
        return
    api_key = str(st.session_state.get("llm_api_key") or "").strip()
    if not api_key:
        st.session_state["google_models_cache"] = []
        st.session_state["google_models_error"] = "尚未設定 Google API key。請到「系統設定 → LLM API Keys」儲存後再試。"
        return
    try:
        svc = LlmService(api_key=api_key, model_name=str(st.session_state.get("google_model_name") or "").strip() or None)
        models = svc.list_models() or []
        names = []
        for m in models:
            name = str((m or {}).get("name") or "").strip()
            methods = (m or {}).get("supported_generation_methods") or []
            if not name:
                continue
            if "generateContent" not in list(methods or []):
                continue
            if "gemini" not in name.lower():
                continue
            names.append(name)
        names = sorted(set(names))
        st.session_state["google_models_cache"] = names
        st.session_state["google_models_error"] = ""
    except Exception as e:
        st.session_state["google_models_cache"] = []
        st.session_state["google_models_error"] = str(e)


def _ensure_openai_model_pref() -> None:
    if st.session_state.get("openai_model_name"):
        return
    user = st.session_state.get("user") or {}
    saved = load_llm_model_for(user, "openai") if user else None
    if saved:
        st.session_state["openai_model_name"] = str(saved)
        return
    env_v = str(os.getenv("OPENAI_MODEL") or "").strip()
    if env_v:
        st.session_state["openai_model_name"] = env_v
        return
    st.session_state["openai_model_name"] = "gpt-4.1-mini"


def _refresh_openai_models() -> None:
    api_key = str(st.session_state.get("llm_api_key") or "").strip()
    if not api_key:
        st.session_state["openai_models_cache"] = []
        st.session_state["openai_models_error"] = "尚未設定 OpenAI API key。請到「系統設定 → LLM API Keys」儲存後再試。"
        return
    try:
        names = fetch_openai_model_ids(api_key)
        st.session_state["openai_models_cache"] = names
        st.session_state["openai_models_error"] = ""
    except Exception as e:
        st.session_state["openai_models_cache"] = []
        st.session_state["openai_models_error"] = str(e)


def _ensure_anthropic_model_pref() -> None:
    if st.session_state.get("anthropic_model_name"):
        return
    user = st.session_state.get("user") or {}
    saved = load_llm_model_for(user, "anthropic") if user else None
    if saved:
        st.session_state["anthropic_model_name"] = str(saved)
        return
    env_v = str(os.getenv("ANTHROPIC_MODEL") or "").strip()
    if env_v:
        st.session_state["anthropic_model_name"] = env_v
        return
    st.session_state["anthropic_model_name"] = "claude-3-5-sonnet-20241022"


def _refresh_anthropic_models() -> None:
    api_key = str(st.session_state.get("llm_api_key") or "").strip()
    if not api_key:
        st.session_state["anthropic_models_cache"] = []
        st.session_state["anthropic_models_error"] = "尚未設定 Anthropic API key。請到「系統設定 → LLM API Keys」儲存後再試。"
        return
    try:
        names = fetch_anthropic_model_ids(api_key)
        st.session_state["anthropic_models_cache"] = names
        st.session_state["anthropic_models_error"] = ""
    except Exception as e:
        st.session_state["anthropic_models_cache"] = []
        st.session_state["anthropic_models_error"] = str(e)


def _render_llm_model_picker_block(
    *,
    provider_id: str,
    section_title: str,
    select_label: str,
    model_state_key: str,
    cache_key: str,
    error_key: str,
    loaded_key: str,
    picker_key: str,
    ensure_pref: Callable[[], None],
    refresh_cache: Callable[[], None],
    format_choice: Callable[[str], str],
) -> None:
    ensure_pref()
    current_full = str(st.session_state.get(model_state_key) or "").strip()
    st.markdown(f"<div class='muted'>{section_title}</div>", unsafe_allow_html=True)

    cached = st.session_state.get(cache_key) or []
    if not isinstance(cached, list):
        cached = []
    if (not cached) and (not st.session_state.get(loaded_key)) and str(st.session_state.get("llm_api_key") or "").strip():
        refresh_cache()
        st.session_state[loaded_key] = True
        cached = st.session_state.get(cache_key) or []

    err = str(st.session_state.get(error_key) or "").strip()
    if err:
        st.warning(err)

    if cached:
        options = list(cached)
        if current_full and current_full not in options:
            options = [current_full] + options
        picked = st.selectbox(
            select_label,
            options=options,
            index=options.index(current_full) if current_full in options else 0,
            format_func=format_choice,
            key=picker_key,
        )
        picked = str(picked or "").strip()
        if picked and picked != current_full:
            st.session_state[model_state_key] = picked
            user = st.session_state.get("user") or {}
            if user:
                save_llm_model_for(user, provider_id, picked)
            st.success(f"已套用：{format_choice(picked)}")
    else:
        st.code(format_choice(current_full) or "（未設定）")


# ── LLM key 同步 ──────────────────────────────────────────────────────────────

def _llm_id_from_label(label: str) -> str:
    s = (label or "").lower()
    if s.startswith("openai"):
        return "openai"
    if s.startswith("anthropic"):
        return "anthropic"
    if s.startswith("google"):
        return "google"
    return "openai"


def _sync_llm_key_from_choice() -> None:
    user = st.session_state.get("user")
    if not user:
        return
    llm_label = st.session_state.get("llm_choice", "")
    llm_id = _llm_id_from_label(llm_label)
    st.session_state["active_llm_id"] = llm_id
    keys = load_llm_api_keys(user)
    st.session_state["llm_api_keys"] = keys
    st.session_state["llm_api_key"] = keys.get(llm_id, "")

# ── 頁面主渲染函式 ──────────────────────────────────────────────────────────

def render_analyze():
    header("發票分析", "上傳發票、選擇 LLM、一鍵產生辨識結果。")

    sb = st.session_state.get("supabase")
    src = st.session_state.get("data_source", "mock")

    # 多張分析結果（每張一個 analysis dict）
    if "analyses" not in st.session_state:
        st.session_state["analyses"] = []
    if "analysis_idx" not in st.session_state:
        st.session_state["analysis_idx"] = 0
    if "img_zoom" not in st.session_state:
        st.session_state["img_zoom"] = 1.0

    chart_rows = get_chart_rows()
    account_name_options = [""] + chart_names_sorted(chart_rows)
    acct_meta = get_account_chart_status()
    if sb is not None:
        if not acct_meta.get("success"):
            st.warning(
                "無法讀取科目對照表。常見原因：表名不符、資料表尚未建立、**RLS 未允許 SELECT**、或 API key 無權限。\n\n"
                f"**診斷**（嘗試表：`{acct_meta.get('table') or '—'}`）→ {acct_meta.get('error') or '未知錯誤'}\n\n"
                "請在 Supabase **Table Editor** 確認實際表名，並設定 `ACCOUNT_CHART_TABLE` 環境變數，或在 "
                "`secrets.toml` 加入 `ACCOUNT_CHART_TABLE = \"你的表名\"` 或 `[supabase]` 底下的 "
                "`account_chart_table = \"你的表名\"`。"
            )
        elif acct_meta.get("error"):
            st.warning(acct_meta["error"])
        elif int(acct_meta.get("row_count") or 0) == 0 and acct_meta.get("table"):
            st.caption(
                f"科目對照表「{acct_meta.get('table')}」目前為 0 筆，請在資料庫新增科目（需有「名稱」類欄位，例如 name／科目名稱）。"
            )
        elif len(account_name_options) <= 1:
            st.caption(
                "查無可用科目名稱：請確認表內有資料，且名稱欄位為 name、subject_name、account_name 或 科目名稱 等。"
            )

    submission_period = _render_submission_month_selector()
    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

    left, right = st.columns([1.05, 0.95], gap="large")

    with left:
        st.markdown("<div class='h2'>輸入區</div>", unsafe_allow_html=True)
        with card():
            uploaded_files = st.file_uploader(
                "上傳發票（可多選）",
                type=["png", "jpg", "jpeg", "webp", "pdf"],
                accept_multiple_files=True,
            )
            st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
            llm = st.selectbox(
                "選擇 LLM",
                ["OpenAI · gpt-4.1-mini", "Anthropic · sonnet", "Google · gemini-flash"],
                index=0,
                key="llm_choice",
                on_change=_sync_llm_key_from_choice,
            )
            llm_id_preview = _llm_id_from_label(llm)
            if llm_id_preview == "openai":
                _render_llm_model_picker_block(
                    provider_id="openai",
                    section_title="OpenAI 模型",
                    select_label="選擇 OpenAI 模型",
                    model_state_key="openai_model_name",
                    cache_key="openai_models_cache",
                    error_key="openai_models_error",
                    loaded_key="openai_models_loaded",
                    picker_key="openai_model_picker",
                    ensure_pref=_ensure_openai_model_pref,
                    refresh_cache=_refresh_openai_models,
                    format_choice=lambda s: str(s or "").strip(),
                )
            elif llm_id_preview == "anthropic":
                _render_llm_model_picker_block(
                    provider_id="anthropic",
                    section_title="Anthropic 模型",
                    select_label="選擇 Claude 模型",
                    model_state_key="anthropic_model_name",
                    cache_key="anthropic_models_cache",
                    error_key="anthropic_models_error",
                    loaded_key="anthropic_models_loaded",
                    picker_key="anthropic_model_picker",
                    ensure_pref=_ensure_anthropic_model_pref,
                    refresh_cache=_refresh_anthropic_models,
                    format_choice=lambda s: str(s or "").strip(),
                )
            elif llm_id_preview == "google":
                _render_llm_model_picker_block(
                    provider_id="google",
                    section_title="Gemini 模型",
                    select_label="選擇 Gemini 模型",
                    model_state_key="google_model_name",
                    cache_key="google_models_cache",
                    error_key="google_models_error",
                    loaded_key="google_models_loaded",
                    picker_key="google_model_picker",
                    ensure_pref=_ensure_google_model_pref,
                    refresh_cache=_refresh_google_models,
                    format_choice=_short_model_name,
                )

            # temperature：預設 0.1（用 widget value 當預設，不要另外寫 session_state，避免 Streamlit 警告/重跑）
            temperature = st.slider(
                "Temperature",
                min_value=0.0,
                max_value=1.0,
                value=0.1,
                step=0.05,
                help="數值越低越穩定；越高越有創造性（但更容易跑偏）。",
                key="llm_temperature",
            )
            if "active_llm_id" not in st.session_state:
                _sync_llm_key_from_choice()

            # Prompt 預設值來自 user_companies.prompt（登入帳號＋公司統編綁定列），
            # 若為空則退回系統預設值。使用者仍可在此 text_area 即時修改本次分析使用的 prompt。
            user_default_prompt = str((st.session_state.get("user") or {}).get("prompt", "") or "")
            prompt_default = user_default_prompt if user_default_prompt.strip() else DEFAULT_ANALYZE_PROMPT
            prompt = st.text_area("Prompt", value=prompt_default, height=140)
            
            st.markdown("<div class='big-primary'>", unsafe_allow_html=True)
            if st.button(
                "一鍵分析",
                type="primary",
                use_container_width=True,
                disabled=(not uploaded_files),
                icon=":material/bolt:",
            ):
                submission_period = get_submission_period_from_session(st.session_state)
                llm_id = _llm_id_from_label(llm)

                results: List[Dict[str, Any]] = []
                files = list(uploaded_files or [])
                total_n = len(files)

                # Loading UI：轉圈圈 + 進度條（逐張更新）
                prog = st.progress(0.0)
                msg = st.empty()
                try:
                    with st.spinner("正在分析發票中，請稍候..."):
                        for i, f in enumerate(files):
                            fn = getattr(f, "name", "") or f"invoice_{i+1}"
                            msg.markdown(f"**處理中**：{i+1}/{total_n}｜{fn}")
                            try:
                                if llm_id == "google":
                                    name0 = (fn or "").strip()
                                    mime0 = str(getattr(f, "type", "") or "").lower()
                                    ext0 = os.path.splitext(name0)[1].lower().lstrip(".")
                                    is_pdf = (ext0 == "pdf") or name0.lower().endswith(".pdf") or ("application/pdf" in mime0)
                                    if is_pdf:
                                        # PDF：逐頁轉圖後擷取（每頁一筆；自動拆分所有頁面）
                                        temp_dir = os.path.join(_ROOT, "temp")
                                        os.makedirs(temp_dir, exist_ok=True)
                                        # Windows 檔名防呆：避免過長/特殊字元導致寫檔失敗
                                        safe_pdf_name = _safe_filename(name0)
                                        if not safe_pdf_name.lower().endswith(".pdf"):
                                            safe_pdf_name = f"{safe_pdf_name}.pdf"
                                        pdf_path = os.path.join(temp_dir, safe_pdf_name)
                                        with open(pdf_path, "wb") as pf:
                                            pf.write(f.getvalue())
                                        img_paths = _pdf_to_page_images(pdf_path, out_dir=temp_dir, max_pages=0)
                                        if not img_paths:
                                            raise RuntimeError("PDF 轉圖失敗：未取得任何頁面。")
                                        msg.markdown(f"**PDF 拆頁完成**：{len(img_paths)} 頁｜{fn}")
                                        for pi, img_path in enumerate(img_paths):
                                            page_name = f"{fn}（第 {pi+1} 頁）"
                                            a_page = run_gemini_extraction_from_image_path(
                                                prompt=prompt,
                                                image_path=img_path,
                                                file_name=page_name,
                                                temperature=float(temperature),
                                                submission_period=submission_period,
                                            )
                                            register_analysis_file_to_import(a_page)
                                            results.append(a_page)
                                        # 本檔案已拆頁加入 results，不再走下面的單張 append
                                        continue
                                    else:
                                        a = run_gemini_extraction(
                                            prompt=prompt,
                                            uploaded_file=f,
                                            temperature=float(temperature),
                                            submission_period=submission_period,
                                        )
                                else:
                                    # 目前只把 accounting/services 的 Gemini 擷取接入；其他供應商先維持 mock
                                    mid = ""
                                    if llm_id == "openai":
                                        mid = str(st.session_state.get("openai_model_name") or "").strip()
                                    elif llm_id == "anthropic":
                                        mid = str(st.session_state.get("anthropic_model_name") or "").strip()
                                    a = run_mock_analysis(
                                        llm=llm,
                                        prompt=prompt,
                                        file_size=len(f.getvalue()),
                                        model_id=mid,
                                        seq=i,
                                    )
                                    if llm_id in ("openai", "anthropic"):
                                        _apply_prompt_deductibility_with_gemini(a, prompt, float(temperature))
                                a["_file_name"] = fn
                                a["_file_ext"] = os.path.splitext(a["_file_name"])[1].lower().lstrip(".")
                                a["_file_bytes"] = f.getvalue()
                                if not a.get("submission_period"):
                                    _apply_submission_period_to_analysis(a, submission_period)
                                register_analysis_file_to_import(a)
                                results.append(a)
                            except Exception as e:
                                # 重要：Google/Gemini 失敗時不要回退到 mock（避免顯示「不正確但看似正常」的假資料）
                                if llm_id == "google":
                                    err_row: Dict[str, Any] = {
                                            "_file_name": fn,
                                            "_file_ext": os.path.splitext(fn)[1].lower().lstrip("."),
                                            "_file_bytes": f.getvalue(),
                                            "llm": llm,
                                            "prompt": prompt,
                                            "invoice": {
                                                "發票號碼": "",
                                                "交易日期": "",
                                                "含稅金額": 0.0,
                                                "賣方統編": "",
                                                "賣方名稱": "",
                                                "品名/備註": "",
                                                "狀態": "辨識失敗（Gemini）",
                                            },
                                            "ai": {"可扣抵": False, "信心": 0.0},
                                            "explain": {
                                                "原因": "Gemini 擷取失敗，未產生可用發票資訊。",
                                                "錯誤": str(e),
                                                "規則": [{"項目": "欄位擷取", "結果": "失敗"}],
                                                "歷史案例": mock_history_cases(),
                                            },
                                        }
                                    _apply_submission_period_to_analysis(err_row, submission_period)
                                    register_analysis_file_to_import(err_row)
                                    results.append(err_row)
                                else:
                                    mid2 = ""
                                    if llm_id == "openai":
                                        mid2 = str(st.session_state.get("openai_model_name") or "").strip()
                                    elif llm_id == "anthropic":
                                        mid2 = str(st.session_state.get("anthropic_model_name") or "").strip()
                                    fallback = run_mock_analysis(
                                        llm=llm,
                                        prompt=prompt,
                                        file_size=len(f.getvalue()),
                                        model_id=mid2,
                                        seq=i,
                                    )
                                    fallback["_file_name"] = fn
                                    fallback["_file_ext"] = os.path.splitext(fn)[1].lower().lstrip(".")
                                    fallback["_file_bytes"] = f.getvalue()
                                    fallback.setdefault("explain", {})
                                    fallback["explain"]["錯誤"] = str(e)
                                    _apply_submission_period_to_analysis(fallback, submission_period)
                                    if llm_id in ("openai", "anthropic"):
                                        _apply_prompt_deductibility_with_gemini(fallback, prompt, float(temperature))
                                    register_analysis_file_to_import(fallback)
                                    results.append(fallback)
                            finally:
                                prog.progress((i + 1) / max(total_n, 1))
                finally:
                    prog.empty()
                    msg.empty()

                for a in results:
                    if not a.get("submission_period"):
                        _apply_submission_period_to_analysis(a, submission_period)
                st.session_state["analyses"] = results
                st.session_state["analysis_idx"] = 0
                st.session_state["analyze_ui_rev"] = int(st.session_state.get("analyze_ui_rev", 0) or 0) + 1
                st.session_state["analyze_save_flash"] = "分析完成！"
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

            # 左側「核對原圖（浮窗）」：與右側選擇的發票同步
            analyses_for_preview = st.session_state.get("analyses") or []
            if analyses_for_preview:
                idx0 = int(st.session_state.get("analysis_idx", 0) or 0)
                idx0 = max(0, min(idx0, len(analyses_for_preview) - 1))
                a0 = analyses_for_preview[idx0]
                file_ext0 = (a0.get("_file_ext") or "").lower()
                file_bytes0 = a0.get("_file_bytes")
                if hasattr(st, "popover"):
                    with st.popover("核對原圖", use_container_width=True):
                        if isinstance(file_bytes0, (bytes, bytearray)) and file_ext0 in ("png", "jpg", "jpeg", "webp"):
                            zoom_key = f"img_zoom_left_{idx0}"
                            if zoom_key not in st.session_state:
                                st.session_state[zoom_key] = 1.0
                            zoom = st.slider(
                                "縮放",
                                min_value=0.5,
                                max_value=3.0,
                                value=float(st.session_state.get(zoom_key, 1.0) or 1.0),
                                step=0.1,
                                key=zoom_key,
                            )
                            _image_viewport(
                                file_bytes=bytes(file_bytes0),
                                ext=file_ext0,
                                caption=a0.get("_file_name", "invoice"),
                                zoom=float(zoom),
                                vw=420,
                                vh=520,
                            )
                        else:
                            st.info("暫無可預覽的原圖（僅支援 png/jpg/jpeg/webp）。")
                else:
                    with st.expander("核對原圖（此版本不支援浮窗，改用展開）", expanded=True):
                        if isinstance(file_bytes0, (bytes, bytearray)) and file_ext0 in ("png", "jpg", "jpeg", "webp"):
                            zoom_key = f"img_zoom_left_{idx0}"
                            if zoom_key not in st.session_state:
                                st.session_state[zoom_key] = 1.0
                            zoom = st.slider(
                                "縮放",
                                min_value=0.5,
                                max_value=3.0,
                                value=float(st.session_state.get(zoom_key, 1.0) or 1.0),
                                step=0.1,
                                key=zoom_key,
                            )
                            _image_viewport(
                                file_bytes=bytes(file_bytes0),
                                ext=file_ext0,
                                caption=a0.get("_file_name", "invoice"),
                                zoom=float(zoom),
                                vw=420,
                                vh=520,
                            )
                        else:
                            st.info("暫無可預覽的原圖（僅支援 png/jpg/jpeg/webp）。")

    with right:
        _save_flash = st.session_state.pop("analyze_save_flash", None)
        if _save_flash:
            st.success(_save_flash)
        st.markdown("<div class='h2'>結果區</div>", unsafe_allow_html=True)
        analyses = st.session_state.get("analyses") or []
        if not analyses:
            st.info("請先上傳並分析。")
            return

        labels = []
        for i, a in enumerate(analyses):
            fn = a.get("_file_name", f"發票 {i+1}")
            inv_no = normalize_invoice_number((a.get("invoice") or {}).get("發票號碼", ""))
            status = (a.get("invoice") or {}).get("狀態", "")
            labels.append(f"{i+1}. {fn}｜{inv_no or '（無號碼）'}｜{status}")

        idx = int(st.session_state.get("analysis_idx", 0) or 0)
        idx = max(0, min(idx, len(analyses) - 1))
        picked = st.selectbox("選擇要查看的發票", options=list(range(len(analyses))), format_func=lambda i: labels[i])
        st.session_state["analysis_idx"] = int(picked)
        analysis = analyses[int(picked)]

        inv = analysis["invoice"]
        ai  = analysis["ai"]

        with card():
            st.markdown("<div class='section-title'>結果摘要</div>", unsafe_allow_html=True)
            _deduct_opts = ("可扣抵", "不可扣抵")
            _ai = analysis.setdefault("ai", {})
            _cur_deduct = "可扣抵" if bool(_ai.get("可扣抵")) else "不可扣抵"
            csum1, csum2 = st.columns([1, 1], gap="large")
            with csum1:
                ded_choice = st.selectbox(
                    "扣抵判定",
                    options=list(_deduct_opts),
                    index=list(_deduct_opts).index(_cur_deduct),
                    key=f"analyze_deductible_{picked}_{st.session_state.get('analyze_ui_rev', 0)}",
                    help="可覆寫 AI 判斷；儲存至資料庫時會寫入 is_deductible。",
                )
                _ai["可扣抵"] = ded_choice == "可扣抵"
                deductible = bool(_ai["可扣抵"])
                dot, label = ("dot-green", "可扣抵") if deductible else ("dot-red", "不可扣抵")
                st.markdown(
                    f"<div class='badge'><span class='dot {dot}'></span>{label}</div>",
                    unsafe_allow_html=True,
                )
                st.caption(f"AI 信心 {float(_ai.get('信心', 0) or 0):.0%}")
                st.progress(float(_ai.get("信心", 0) or 0))
            with csum2:
                st.markdown(
                    f"<div class='muted'>LLM</div><div class='mono' style='font-weight:800;'>{analysis['llm']}</div>",
                    unsafe_allow_html=True,
                )

            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
            tabs = st.tabs(["發票明細", "規則/理由", "操作"])

            with tabs[0]:
                r1c1, r1c2 = st.columns(2, gap="medium")
                inv_no = r1c1.text_input(
                    "發票號碼",
                    value=normalize_invoice_number(inv.get("發票號碼", "")),
                )
                inv_date = r1c2.text_input("交易日期", value=inv.get("交易日期", ""))

                r2c1, r2c2 = st.columns(2, gap="medium")
                invoice_type_opts = ["", "三聯式統一發票", "三聯式收銀機統一發票扣抵聯", "電子發票", "二聯式收銀機統一發票"]
                invoice_type = r2c1.selectbox(
                    "發票類型",
                    options=invoice_type_opts,
                    index=invoice_type_opts.index(inv.get("發票類型", "")) if inv.get("發票類型", "") in invoice_type_opts else 0,
                )
                cur_acct = str(inv.get("會計科目", "") or "").strip()
                snapped_acct = best_match_account_name(
                    cur_acct, chart_rows, desc=str(inv.get("品名/備註", "") or "")
                )
                sel_acct = snapped_acct if snapped_acct in account_name_options else ""
                acct_index = (
                    account_name_options.index(sel_acct) if sel_acct in account_name_options else 0
                )
                account = r2c2.selectbox(
                    "會計科目",
                    options=account_name_options,
                    index=acct_index,
                    help="僅能選科目對照表內的名稱；分析後會依 AI 建議與品名自動對到最相近科目。",
                    key=f"analyze_account_{picked}_{st.session_state.get('analyze_ui_rev', 0)}",
                )

                r3c1, r3c2 = st.columns(2, gap="medium")
                seller_name = r3c1.text_input("賣方名稱", value=inv.get("賣方名稱", ""))
                seller_tax_id = r3c2.text_input("賣方統編", value=inv.get("賣方統編", ""))

                buyer_tax_ui = st.text_input(
                    "買方統編",
                    value=str(inv.get("買方統編", "") or ""),
                    help="寫入資料庫欄位 buyer_tax_id（本公司統一編號）。",
                )

                r4c1, r4c2, r4c3 = st.columns([1, 1, 1], gap="medium")
                inv_taxable_ui = r4c1.number_input(
                    "應稅金額",
                    value=_truncate_amount(inv.get("應稅金額", 0.0)),
                    format="%.0f",
                    step=1.0,
                )
                inv_tax_ui = r4c2.number_input(
                    "稅額",
                    value=_truncate_amount(inv.get("稅額", 0.0)),
                    format="%.0f",
                    step=1.0,
                )
                inv_amt = r4c3.number_input(
                    "含稅金額",
                    value=_truncate_amount(inv.get("含稅金額", 0.0)),
                    format="%.0f",
                    step=1.0,
                )

                status = st.text_input("狀態", value=inv.get("狀態", ""))

                note = st.text_input("品名/備註", value=inv.get("品名/備註", ""))

                # 讓使用者在明細頁的修改能保留（切換分頁/切換發票/批次儲存時也會帶到）
                try:
                    (analysis.get("invoice") or {}).update(
                        {
                            "發票號碼": normalize_invoice_number(inv_no),
                            "交易日期": inv_date,
                            "發票類型": invoice_type,
                            "會計科目": account,
                            "賣方名稱": seller_name,
                            "賣方統編": seller_tax_id,
                            "買方統編": normalize_buyer_tax_id(buyer_tax_ui),
                            "應稅金額": _truncate_amount(inv_taxable_ui),
                            "稅額": _truncate_amount(inv_tax_ui),
                            "含稅金額": _truncate_amount(inv_amt),
                            "狀態": status,
                            "品名/備註": note,
                        }
                    )
                except Exception:
                    pass

            with tabs[1]:
                exp = analysis.get("explain", {})
                st.markdown(f"**原因**：{exp.get('原因','')}")
                if exp.get("錯誤"):
                    st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)
                    st.error(exp.get("錯誤"))
                rules = exp.get("規則", [])
                if rules:
                    st.dataframe(pd.DataFrame(rules), use_container_width=True, hide_index=True)
                cases = exp.get("歷史案例", [])
                if cases:
                    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
                    st.markdown("**相似案例**")
                    st.dataframe(pd.DataFrame(cases), use_container_width=True, hide_index=True)

            with tabs[2]:
                st.markdown("<div class='muted'>提示：若為 Supabase 模式，將同步寫入雲端。</div>", unsafe_allow_html=True)
                st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
                def _analysis_to_row(a: Dict[str, Any]) -> Dict[str, Any]:
                    inv0 = a.get("invoice") or {}
                    raw_structured = a.get("llm_structured")
                    desc0 = str(inv0.get("品名/備註", "") or "")
                    invoice_type0 = str(inv0.get("發票類型", "") or "")
                    account0 = best_match_account_name(
                        str(inv0.get("會計科目", "") or "").strip(),
                        chart_rows,
                        desc=desc0,
                    )

                    # 金額欄位：優先採用發票讀取結果（llm_structured），無條件捨去小數
                    inv_amts = _truncate_invoice_amounts(inv0)
                    total = _truncate_amount(inv_amts.get("含稅金額"), 0.0)
                    taxable = _truncate_amount(inv_amts.get("應稅金額"), 0.0)
                    tax = _truncate_amount(inv_amts.get("稅額"), 0.0)
                    if isinstance(raw_structured, dict):
                        if not taxable:
                            taxable = _truncate_amount(raw_structured.get("應稅金額"), 0.0)
                        if not tax:
                            tax = _truncate_amount(raw_structured.get("稅額"), 0.0)
                        if not total:
                            total = _truncate_amount(raw_structured.get("總計"), 0.0)
                        if not total and (taxable or tax):
                            total = _truncate_amount(taxable + tax)

                    # 若仍缺漏，再用含稅金額反推
                    if (not taxable) and total:
                        taxable = _truncate_amount(total / 1.05)
                    if (not tax) and total:
                        tax = _truncate_amount(total - taxable)

                    btid = _buyer_tax_id_for_row(inv0, raw_structured)
                    period = _period_for_save(a)
                    row_out = {
                        **_invoice_db_fields_from_period(period),
                        **_invoice_uploader_field(),
                        "invoice_number": normalize_invoice_number(inv0.get("發票號碼", "")),
                        "invoice_type": invoice_type0,
                        "account": account0,
                        "buyer_tax_id": btid,
                        "buyer_name": (st.session_state.get("user") or {}).get("org", ""),
                        "seller_tax_id": str(inv0.get("賣方統編", "") or ""),
                        "seller_name": str(inv0.get("賣方名稱", "") or ""),
                        "transaction_date": str(inv0.get("交易日期", "") or ""),
                        "taxable_amount": taxable,
                        "tax_amount": tax,
                        "total_amount": total,
                        "description": desc0,
                        "invoice_image_path": "",
                        "system_status": str(inv0.get("狀態", "") or ""),
                        "is_deductible": _is_deductible_from_analysis(a),
                    }
                    row_out["uploaded_at"] = submission_uploaded_at_iso(period)
                    return row_out

                def _save_row(row: Dict[str, Any], *, period: Any = None) -> bool:
                    if sb is None:
                        st.error("無 Supabase 連線，無法儲存至雲端。")
                        return False
                    p = period if period is not None else period_from_invoice_row(row)
                    if p is None:
                        p = _period_for_save()
                    return insert_invoice_to_supabase(sb, dict(row or {}), period=p)

                csave1, csave2 = st.columns([1, 1], gap="medium")

                with csave1:
                    if st.button("儲存目前這張", type="primary", use_container_width=True, icon=":material/save:"):
                        # 目前畫面上的輸入欄位（可能已被使用者手動修正）優先
                        inv_payload_total = _truncate_amount(inv_amt)
                        inv_payload_taxable = _truncate_amount(inv_taxable_ui)
                        inv_payload_tax = _truncate_amount(inv_tax_ui)

                        raw_structured = analysis.get("llm_structured")
                        desc = str(note or "")
                        invoice_type_to_save = str(invoice_type or "")
                        account_to_save = str(account or "")

                        # 稅額/應稅金額：以讀取的發票資訊為準；缺漏才反推（反推後亦捨去小數）
                        if (not inv_payload_taxable) and inv_payload_total:
                            inv_payload_taxable = _truncate_amount(inv_payload_total / 1.05)
                        if (not inv_payload_tax) and inv_payload_total:
                            inv_payload_tax = _truncate_amount(inv_payload_total - inv_payload_taxable)

                        _btid = _buyer_tax_id_for_row(
                            {**(inv or {}), "買方統編": normalize_buyer_tax_id(buyer_tax_ui)},
                            raw_structured,
                        )
                        period_save = _period_for_save(analysis)
                        new_row = {
                            **_invoice_db_fields_from_period(period_save),
                            **_invoice_uploader_field(),
                            "invoice_number": normalize_invoice_number(inv_no),
                            "invoice_type": invoice_type_to_save,
                            "account": account_to_save,
                            "buyer_tax_id": _btid,
                            "buyer_name": (st.session_state.get("user") or {}).get("org", ""),
                            "seller_tax_id": seller_tax_id,
                            "seller_name": seller_name,
                            "transaction_date": inv_date,
                            "taxable_amount": inv_payload_taxable,
                            "tax_amount": inv_payload_tax,
                            "total_amount": inv_payload_total,
                            "description": desc,
                            "invoice_image_path": "",
                            "system_status": status,
                            "is_deductible": _is_deductible_from_analysis(analysis),
                            "uploaded_at": submission_uploaded_at_iso(period_save),
                        }

                        if _save_row(new_row, period=period_save):
                            _refresh_analyze_page_after_save("已儲存至 Supabase 🎉", sb)

                with csave2:
                    if st.button("全部儲存至資料庫", use_container_width=True, icon=":material/cloud_upload:"):
                        all_rows = [_analysis_to_row(a) for a in analyses]
                        total_n = len(all_rows)
                        remote_n = 0
                        fail_n = 0

                        prog = st.progress(0.0)
                        msg = st.empty()

                        for i, row in enumerate(all_rows):
                            msg.write(f"寫入中：{i+1}/{total_n}")
                            if _save_row(row, period=_period_for_save(analyses[i])):
                                remote_n += 1
                            else:
                                fail_n += 1
                            prog.progress((i + 1) / max(total_n, 1))

                        msg.empty()
                        if fail_n:
                            flash = f"完成：Supabase 成功 {remote_n}/{total_n} 筆，失敗 {fail_n} 筆（請查看上方錯誤訊息）。"
                        else:
                            flash = f"完成：已寫入 Supabase {remote_n}/{total_n} 筆。"
                        if remote_n:
                            _refresh_analyze_page_after_save(flash, sb)
                        elif fail_n:
                            st.error(flash)

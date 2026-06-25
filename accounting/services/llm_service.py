import google.generativeai as genai
import json
import os
import datetime
import re
from typing import Any, Dict, List, Optional

from PIL import Image

from utils.invoice_fmt import normalize_invoice_number
from utils.submission_period import compute_submission_period, parse_roc_yyyymm, period_to_structured_fields


class LlmService:
    def __init__(self, api_key: str | None = None, model_name: str | None = None):
        """
        - api_key: 由 UI/偏好設定傳入（預設不再依賴 .env）
        - model_name: 可選；未提供則採用 env 的 GEMINI_MODEL 或預設值
        """
        self.api_key = str(api_key or "").strip()
        if self.api_key:
            genai.configure(api_key=self.api_key)

        # Model name can be configured via env var (must match ListModels output, e.g. "models/gemini-3-flash-preview")
        self.model_name = (str(model_name or "").strip() or os.getenv("GEMINI_MODEL") or "models/gemini-3-flash-preview")
        self.model = genai.GenerativeModel(self.model_name)

    def _classify_invoice_type(self, text: str) -> str:
        """
        依據文字內容判斷「發票種類」。
        找不到任何關鍵字則回傳「其他未知憑證」。
        """
        t = (text or "").strip()
        if not t:
            return "其他未知憑證"

        # 先做輕量正規化：去空白、全形括號統一
        t_norm = (
            t.replace(" ", "")
            .replace("\u3000", "")
            .replace("（", "(")
            .replace("）", ")")
        )

        # 依「越具體越先比」的順序
        rules = [
            (
                "三聯式收銀機統一發票扣抵聯",
                [
                    "三聯式收銀機統一發票扣抵聯",
                    "收銀機統一發票(三聯副聯式扣抵聯)",
                    "收銀機統一發票(三聯式扣抵聯)",
                    "收銀機統一發票三聯扣抵聯",
                ],
            ),
            ("統一發票(三聯式)", ["統一發票(三聯式)", "三聯式統一發票", "統一發票三聯式"]),
            ("收銀機統一發票", ["收銀機統一發票"]),
            ("電子發票證明聯、電子發票", ["電子發票證明聯", "電子發票"]),
        ]

        for label, keywords in rules:
            for kw in keywords:
                if kw.replace(" ", "") in t_norm:
                    return label

        return "其他未知憑證"

    def list_models(self):
        """
        Returns a list of dicts: {name, supported_generation_methods}.
        Helpful for resolving 'model not found / not supported' errors.
        """
        out = []
        for m in genai.list_models():
            out.append(
                {
                    "name": getattr(m, "name", ""),
                    "supported_generation_methods": list(
                        getattr(m, "supported_generation_methods", []) or []
                    ),
                }
            )
        return out

    def evaluate_deductibility(
        self,
        user_prompt: str,
        invoice_summary: Dict[str, Any],
        temperature: float = 0.1,
    ) -> Dict[str, Any]:
        """
        依「發票分析」頁面使用者輸入的準則（user_prompt）與已擷取／摘要後的發票欄位，
        判斷進項是否可扣抵，回傳 JSON：可扣抵、信心、原因、規則（陣列）。
        僅文字推論，不依賴圖片。
        """
        out: Dict[str, Any] = {}
        if not self.api_key:
            return out
        up = str(user_prompt or "").strip()
        inv_json = json.dumps(invoice_summary or {}, ensure_ascii=False)
        judge_prompt = f"""你是台灣加值型營業稅（進項憑證）審核顧問。

使用者在「發票分析」頁面提供的判斷準則／提示如下（請優先依此解讀；若準則未明確寫扣抵與否，再輔以我國常見實務與憑證形式合理推斷，並在原因中說明依據）：
---
{up if up else "（未提供額外準則，請依實務與憑證內容推斷是否可作為進項可扣抵憑證。）"}
---

已擷取之發票欄位（JSON）：
{inv_json}

請只回傳一個 JSON 物件（不要 markdown、不要註解），鍵名必須為：
- "可扣抵": 布林值 true 或 false（指本憑證是否符合進項扣抵意旨／可作為申報扣抵之依據；若資訊不足請 false 並在原因說明）
- "信心": 0 到 1 之間的數字
- "原因": 一段簡短繁體中文，說明為何可或不可扣抵（須呼應使用者準則或實務）
- "規則": 陣列；每個元素為物件，且必含字串鍵 "項目" 與 "結果"，條列你做的檢查步驟（例如憑證種類、是否為扣抵聯、用途／科目與準則對照等）
"""
        try:
            resp = self.model.generate_content(
                [judge_prompt],
                generation_config={"temperature": float(temperature)},
            )
            resp_text = (getattr(resp, "text", None) or "").strip()
            if not resp_text:
                return out
            json_text = self._extract_json_text(resp_text)
            data = json.loads(json_text) if json_text else {}
            if not isinstance(data, dict):
                return out

            ok = data.get("可扣抵")
            if ok is None:
                ok = data.get("deductible")
            if isinstance(ok, str):
                ok = ok.strip().lower() in ("true", "1", "yes", "是", "可")

            conf = data.get("信心", data.get("confidence", 0.65))
            try:
                conf_f = float(conf)
            except Exception:
                conf_f = 0.65
            conf_f = max(0.0, min(1.0, conf_f))

            reason = str(data.get("原因", data.get("reason", "")) or "").strip()
            rules_raw = data.get("規則", data.get("rules", []))
            rules: List[Dict[str, str]] = []
            if isinstance(rules_raw, list):
                for item in rules_raw:
                    if isinstance(item, dict):
                        p = str(item.get("項目", item.get("item", "")) or "").strip()
                        r = str(item.get("結果", item.get("result", "")) or "").strip()
                        if p or r:
                            rules.append({"項目": p or "（項目）", "結果": r or "（結果）"})
                    elif isinstance(item, str) and item.strip():
                        rules.append({"項目": "說明", "結果": item.strip()})

            out["可扣抵"] = bool(ok) if ok is not None else False
            out["信心"] = conf_f
            out["原因"] = reason
            out["規則"] = rules
        except Exception:
            return {}
        return out

    def _extract_json_text(self, text: str) -> str:
        """
        Gemini 有時會回覆額外文字或 Markdown code fence。
        這裡盡量萃取出可被 json.loads 解析的 JSON 片段。
        """
        if not text:
            return ""

        t = text.strip()
        t = re.sub(r"^\s*```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```\s*$", "", t)
        t = t.strip()

        if not (t.startswith("{") and t.endswith("}")):
            m = re.search(r"\{[\s\S]*\}", t)
            if m:
                t = m.group(0).strip()
        return t

    def classify_account(self, invoice_context: dict, temperature: float = 0.1) -> str:
        """
        使用 Gemini 依據已擷取欄位推斷「會計科目」。
        - 僅回傳單一科目名稱字串；不確定則回傳空字串。
        """
        try:
            if not self.api_key:
                return ""

            ctx = invoice_context or {}
            # 盡量只給必要欄位，減少 token
            payload = {
                "賣方公司名稱": ctx.get("賣方公司名稱", ""),
                "賣方統編": ctx.get("賣方統編", ""),
                "科目摘要": ctx.get("科目摘要", ""),
                "發票種類": ctx.get("發票種類", ""),
                "交易日期": ctx.get("交易日期", ""),
                "總計": ctx.get("總計", ""),
            }

            prompt = """
你是台灣公司專業會計師。請根據輸入的發票資訊，判斷「最可能的會計科目」(expense account)，以及判斷會計科目的信心度。
要求：
- 只回傳 JSON，格式：{"會計科目":"...","信心度":0.0-100.0}。
- 信心度 ≥ 80% → 自動入帳；50-80% → 提示使用者確認；< 50% → 標記為待人工審核。
- 會計科目請用常見、簡短、易懂的科目名稱（例如：文具用品費、交通費、郵電費、水電費、交際費、差旅費、修繕費、廣告費、租金支出、保險費、雜項購置/設備、雲端/軟體訂閱費、外包服務費、印刷費等）。
- 若資訊不足無法合理推斷，請回傳空字串，例如：{"會計科目":"","信心度":0.0}。
"""

            resp = self.model.generate_content(
                [prompt, json.dumps(payload, ensure_ascii=False)],
                generation_config={"temperature": float(temperature)},
            )
            resp_text = (getattr(resp, "text", None) or "").strip()
            json_text = self._extract_json_text(resp_text)
            data = json.loads(json_text) if json_text else {}
            acct = str((data or {}).get("會計科目", "") or "").strip()
            # 防呆：避免模型回傳太多文字
            if len(acct) > 30:
                acct = acct[:30].strip()
            return acct
        except Exception:
            return ""

    def _submission_yyyymm(self, submission_yyyymm: Optional[str] = None) -> str:
        s = str(submission_yyyymm or "").strip()
        if s:
            return s
        now = datetime.datetime.now()
        return f"{int(now.year) - 1911:03d}{int(now.month):02d}"

    def structure_data(
        self,
        image_path,
        file_name: str = "",
        temperature: float = 0.1,
        submission_yyyymm: Optional[str] = None,
    ):
        prompt = f"""
        你是一個專業的發票資料提取助手。請從這張發票圖片中，擷取指定的資訊，並以 JSON 格式回傳。
        若資訊不確定或有些模糊，請盡量推測並「照填」，不要輕易省略或留白。如果該欄位真的完全找不到，請填入空字串 ""。

        請盡可能提取以下資訊：
        - 發票號碼 (2 碼英文 + 8 碼數字，共 10 碼連續字串，不要使用連字號「-」)
        - 買方統編 (8碼數字)
        - 買方公司名稱
        - 賣方統編 (8碼數字)
        - 賣方公司名稱
        - 交易日期 (YYYY-MM-DD)
        - 應稅金額 (純數字)
        - 稅額 (純數字，若無請填空字串)
        - 總計 (純數字)
        - 科目摘要 (購買商品的細項)
        - 會計科目（請根據發票內容判斷最可能的會計科目；若無法判斷請填空字串 ""）
        - 發票種類（請從圖片文字判斷發票種類，回傳分類結果；可用值如下：
          1) 電子發票證明聯、電子發票
          2) 統一發票(三聯式)
          3) 收銀機統一發票
          4) 三聯式收銀機統一發票扣抵聯
          若無法判斷請填 "其他未知憑證"）

        請只回傳 JSON，不要包含其他文字或 Markdown 格式標籤（例如 ```json）。
        """

        structured_data = {}
        try:
            if not self.api_key:
                raise RuntimeError("未設定 Google LLM API Key（請到「系統設定 → LLM API Keys」儲存 Google key）。")

            img = Image.open(image_path)
            response = self.model.generate_content(
                [prompt, img],
                generation_config={"temperature": float(temperature)},
            )

            response_text = (getattr(response, "text", None) or "").strip()
            if not response_text:
                raise RuntimeError("Gemini 回傳內容為空（可能是 API 錯誤、額度不足或回覆被阻擋）")

            # 嘗試解析 JSON
            json_text = self._extract_json_text(response_text)
            try:
                extracted_data = json.loads(json_text)
            except Exception as je:
                raise RuntimeError(f"JSON 解析失敗：{je}\n---\n原始回覆：\n{response_text}") from je

            # 處理計算和預設值（送件年月以 UI 選擇為準）
            yyyymm = self._submission_yyyymm(submission_yyyymm)
            structured_data["送件年月"] = yyyymm
            sub_dt = parse_roc_yyyymm(yyyymm)
            if sub_dt:
                structured_data.update(period_to_structured_fields(compute_submission_period(sub_dt)))

            # 2. 其他欄位
            structured_data["發票號碼"] = normalize_invoice_number(extracted_data.get("發票號碼", ""))
            structured_data["買方統編"] = extracted_data.get("買方統編", "")
            structured_data["買方公司名稱"] = extracted_data.get("買方公司名稱", "")
            structured_data["賣方統編"] = extracted_data.get("賣方統編", "")
            structured_data["賣方公司名稱"] = extracted_data.get("賣方公司名稱", "")
            structured_data["交易日期"] = extracted_data.get("交易日期", "")

            # 金額處理
            taxable_amount_str = str(extracted_data.get("應稅金額", "")).replace(",", "")
            taxable_amount = float(taxable_amount_str) if taxable_amount_str.replace(".", "", 1).isdigit() else 0.0
            structured_data["應稅金額"] = taxable_amount

            tax_amount_str = str(extracted_data.get("稅額", "")).replace(",", "")
            if tax_amount_str.replace(".", "", 1).isdigit():
                tax_amount = float(tax_amount_str)
            else:
                tax_amount = round(taxable_amount * 0.05) if taxable_amount else 0.0
            structured_data["稅額"] = tax_amount

            total_amount_str = str(extracted_data.get("總計", "")).replace(",", "")
            structured_data["總計"] = float(total_amount_str) if total_amount_str.replace(".", "", 1).isdigit() else 0.0

            # 確保科目摘要一定是字串 (如果 LLM 回傳了 list，則合併成字串)
            item_summary = extracted_data.get("科目摘要", "")
            if isinstance(item_summary, list):
                structured_data["科目摘要"] = ", ".join([str(item) for item in item_summary])
            else:
                structured_data["科目摘要"] = str(item_summary)

            # 發票種類：優先用 LLM 回傳欄位；沒有就用關鍵字分類
            invoice_type = str(extracted_data.get("發票種類", "") or "").strip()
            if not invoice_type or invoice_type in ("N/A", "NA", "null", "None"):
                # 使用原始回覆 + JSON 內容做一次關鍵字分類（避免 LLM 漏欄）
                blob = response_text + "\n" + json.dumps(extracted_data, ensure_ascii=False)
                invoice_type = self._classify_invoice_type(blob)
            structured_data["發票種類"] = invoice_type

            # 會計科目：優先使用 LLM 圖片擷取；若缺漏，則用文字二次判斷補齊
            acct0 = str(extracted_data.get("會計科目", "") or "").strip()
            if not acct0 or acct0 in ("N/A", "NA", "null", "None"):
                acct0 = self.classify_account(
                    {
                        "賣方公司名稱": structured_data.get("賣方公司名稱", ""),
                        "賣方統編": structured_data.get("賣方統編", ""),
                        "科目摘要": structured_data.get("科目摘要", ""),
                        "發票種類": structured_data.get("發票種類", ""),
                        "交易日期": structured_data.get("交易日期", ""),
                        "總計": structured_data.get("總計", ""),
                    },
                    temperature=float(temperature),
                )
            structured_data["會計科目"] = acct0

            structured_data["發票檔案"] = file_name

        except Exception as e:
            err_msg = str(e)
            # 若是模型 404/不支援，附上可用模型提示
            if "Call ListModels" in err_msg or "ListModels" in err_msg or "not found" in err_msg:
                try:
                    models = self.list_models()
                    candidates = [
                        m["name"]
                        for m in models
                        if "generateContent" in (m.get("supported_generation_methods") or [])
                    ]
                    if candidates:
                        err_msg += "\n\n可用模型（支援 generateContent）例如：\n- " + "\n- ".join(
                            candidates[:20]
                        )
                except Exception:
                    pass

            print(f"Error during LLM extraction: {err_msg}")
            yyyymm = self._submission_yyyymm(submission_yyyymm)
            period_fields: Dict[str, str] = {"送件年月": yyyymm}
            sub_dt = parse_roc_yyyymm(yyyymm)
            if sub_dt:
                period_fields.update(period_to_structured_fields(compute_submission_period(sub_dt)))
            structured_data = {
                **period_fields,
                "發票號碼": "",
                "買方統編": "",
                "買方公司名稱": "",
                "賣方統編": "",
                "賣方公司名稱": "",
                "交易日期": "",
                "應稅金額": 0.0,
                "稅額": 0.0,
                "總計": 0.0,
                "科目摘要": "",
                "發票種類": "其他未知憑證",
                "會計科目": "",
                "發票檔案": file_name,
                "__error": err_msg,
            }

        return structured_data

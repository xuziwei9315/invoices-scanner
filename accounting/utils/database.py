import re
import streamlit as st
import pandas as pd
from typing import Optional, Any, Dict, List, Tuple

try:
    from supabase import create_client
    _SUPABASE_AVAILABLE = True
except ImportError:
    _SUPABASE_AVAILABLE = False

from pathlib import Path
import os

try:
    import tomllib  # py>=3.11
except Exception:  # pragma: no cover
    tomllib = None  # type: ignore

try:
    import tomli  # type: ignore
except Exception:  # pragma: no cover
    tomli = None  # type: ignore


def _read_toml(path: Path) -> Dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    b = path.read_bytes()
    if tomllib is not None:
        return tomllib.loads(b.decode("utf-8"))
    if tomli is not None:
        return tomli.loads(b.decode("utf-8"))
    return {}


def get_supabase_config() -> Dict[str, str]:
    """
    取得 Supabase 設定（不回傳到 UI 的敏感值僅在程式內使用）。

    來源優先序：
    1) Streamlit st.secrets（要求 `.streamlit/secrets.toml` 在啟動工作目錄）
    2) 專案內 `accounting/.streamlit/secrets.toml`（相容目前 repo 結構）
    3) 環境變數 `SUPABASE_URL` / `SUPABASE_KEY` / `SUPABASE_SERVICE_ROLE_KEY`
    """
    # 1) st.secrets
    try:
        url = str(st.secrets["supabase"]["url"]).strip()
        key = (
            str(st.secrets["supabase"].get("service_role_key") or "").strip()
            or str(st.secrets["supabase"].get("service_role") or "").strip()
            or str(st.secrets["supabase"]["key"]).strip()
        )
        if url and key:
            return {"url": url, "key": key, "source": "streamlit_secrets"}
    except Exception:
        pass

    # 2) accounting/.streamlit/secrets.toml
    here = Path(__file__).resolve()
    accounting_root = here.parents[1]  # .../accounting
    bundled = accounting_root / ".streamlit" / "secrets.toml"
    try:
        data = _read_toml(bundled)
        sb = data.get("supabase") if isinstance(data, dict) else None
        if isinstance(sb, dict):
            url = str(sb.get("url") or "").strip()
            key = (
                str(sb.get("service_role_key") or "").strip()
                or str(sb.get("service_role") or "").strip()
                or str(sb.get("key") or "").strip()
            )
            if url and key:
                return {"url": url, "key": key, "source": "accounting_secrets_toml"}
    except Exception:
        pass

    # 3) env vars
    url = str(os.environ.get("SUPABASE_URL") or "").strip()
    key = (
        str(os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
        or str(os.environ.get("SUPABASE_KEY") or "").strip()
    )
    if url and key:
        return {"url": url, "key": key, "source": "env"}

    return {"url": "", "key": "", "source": "missing"}

def get_supabase() -> Optional[Any]:
    """獲取 Supabase 客戶端"""
    if not _SUPABASE_AVAILABLE: 
        return None
    try:
        cfg = get_supabase_config()
        url = cfg.get("url", "")
        key = cfg.get("key", "")
        if not url or not key:
            return None
        return create_client(str(url), str(key))
    except Exception as e:
        # st.error(f"Supabase 設定讀取失敗：{e}")
        return None

def fetch_user_from_supabase(client: Any, username: str) -> Optional[Dict[str, Any]]:
    """
    從 account sys.users 表讀取使用者資料。
    - 表：account sys.users
    - 欄位：name (帳號), password (密碼)
    """
    try:
        # 依錯誤訊息：PostgREST 只暴露 public / graphql_public
        # 因此這裡固定讀取 public.users（或你在 public 建立的 users view）
        resp = client.table("users").select("*").eq("name", username).limit(1).execute()
        if resp.data and len(resp.data) > 0:
            return dict(resp.data[0])
        return None
    except Exception as e:
        st.warning(
            "Supabase 讀取 users 失敗："
            f"{e}\n"
            "（注意：Supabase API 預設只暴露 public schema，請確認 users 表/檢視表位於 public.users）"
        )
        return None


_USER_COMPANY_TAX_ID_COLUMNS: Tuple[str, ...] = (
    "company_tax_id",
    "company__tax_id",
    "conpany__tax_id",
)


def _user_company_row_matches_tax(row: Dict[str, Any], tax_normalized: str) -> bool:
    """比對 user_companies 列上可能的統編欄位（與輸入皆經 normalize_buyer_tax_id）。"""
    from utils.invoice_fmt import normalize_buyer_tax_id

    for col in _USER_COMPANY_TAX_ID_COLUMNS:
        if col not in row:
            continue
        if normalize_buyer_tax_id(row.get(col)) == tax_normalized:
            return True
    return False


def fetch_user_company_binding(
    client: Any, username: str, tax_normalized: str
) -> Optional[Dict[str, Any]]:
    """
    自 user_companies 確認 user_name 與公司統編綁定。
    統編可比對欄位：company_tax_id、company__tax_id、conpany__tax_id（後兩者為常見 legacy 命名）。
    """
    if not tax_normalized:
        return None
    u = (username or "").strip()
    if not u:
        return None
    try:
        resp = (
            client.table("user_companies")
            .select("*")
            .eq("user_name", u)
            .execute()
        )
    except Exception as e:
        st.warning(
            "Supabase 讀取 user_companies 失敗："
            f"{e}\n"
            "（請確認 public.user_companies 已建立，且含 user_name 與統編欄位）"
        )
        return None
    for raw in resp.data or []:
        row = dict(raw)
        if _user_company_row_matches_tax(row, tax_normalized):
            return row
    return None


def verify_login(
    client: Any,
    username: str,
    password: str,
    company_tax_id_input: str,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    驗證 users 帳密，並確認 user_companies 中 user_name／統編與輸入一致。
    回傳 (使用者字典, 錯誤訊息)；成功時錯誤訊息為空字串。
    """
    from utils.invoice_fmt import normalize_buyer_tax_id

    u = (username or "").strip()
    tax_n = normalize_buyer_tax_id(company_tax_id_input)
    if not tax_n:
        return None, "請輸入有效的公司統一編號（8 碼數字）。"

    row = fetch_user_from_supabase(client, username=u)
    if not row:
        return None, "帳號或密碼錯誤，或使用者不存在。"
    stored = str(row.get("password", ""))
    if stored != str(password):
        return None, "帳號或密碼錯誤，或使用者不存在。"

    binding = fetch_user_company_binding(client, u, tax_n)
    if not binding:
        return None, "公司統編與帳號綁定資料不符，請確認 user_companies 的 user_name 與統編欄位。"

    user_out: Dict[str, Any] = {
        "id": row.get("id"),
        "username": row.get("name", u),
        "name": row.get("name") or u,
        "role": row.get("role") or "User",
        "org": row.get("org") or "",
        # 進項發票之買方統編（invoices.buyer_tax_id）；users 表可擇一欄位：buyer_tax_id / tax_id / org_tax_id
        "buyer_tax_id": row.get("buyer_tax_id") or row.get("tax_id") or row.get("org_tax_id") or "",
        # 預設 Prompt：來自 user_companies（帳號＋公司統編綁定列）
        "prompt": str(binding.get("prompt") or ""),
        "user_company_id": binding.get("id"),
        # 本次登入經 user_companies 驗證的統編（正規化後 8 碼內）
        "verified_company_tax_id": tax_n,
    }
    return user_out, ""

def fetch_invoices_from_supabase(client: Any) -> pd.DataFrame:
    """
    從資料庫讀取所有發票資料。
    排序依據改為 transaction_date (發票日期)，這在發票系統中較常見。
    """
    try:
        # 修改點：將原本報錯的 "分析時間" 改為 "transaction_date" 或你的主鍵
        # 這裡會讀取 * (所有欄位)
        resp = client.table("invoices").select("*").order("transaction_date", desc=True).execute()
        
        if resp.data:
            df = pd.DataFrame(resp.data)
            
            # 由於你現在改用英文欄位，原本針對 "AI信心" 的 rename 可以移除
            # 或者改為你需要的格式化邏輯
            return df
        
        return pd.DataFrame()
    except Exception as e:
        # 這裡會捕捉到欄位名稱錯誤並顯示提示
        st.warning(f"Supabase 讀取失敗：{e}")
        return pd.DataFrame()

def _account_chart_table_candidates() -> List[str]:
    """
    科目對照表表名候選（先後嘗試）：環境變數 / secrets / 預設。
    """
    found: List[str] = []

    def _push(t: str) -> None:
        t = (t or "").strip()
        if t and t not in found:
            found.append(t)

    _push(os.environ.get("ACCOUNT_CHART_TABLE") or "")
    try:
        _push(str(st.secrets.get("ACCOUNT_CHART_TABLE") or ""))
    except Exception:
        pass
    try:
        sb = st.secrets.get("supabase")
        if isinstance(sb, dict):
            _push(str(sb.get("account_chart_table") or sb.get("ACCOUNT_CHART_TABLE") or ""))
    except Exception:
        pass
    here = Path(__file__).resolve()
    bundled = here.parents[1] / ".streamlit" / "secrets.toml"
    data = _read_toml(bundled)
    if isinstance(data, dict):
        _push(str(data.get("ACCOUNT_CHART_TABLE") or ""))
        sb2 = data.get("supabase")
        if isinstance(sb2, dict):
            _push(str(sb2.get("account_chart_table") or sb2.get("ACCOUNT_CHART_TABLE") or ""))
    # 與 Table Editor 常見中文表名一致（若未設定 ACCOUNT_CHART_TABLE 仍會自動嘗試）
    _push("科目對照表")
    for d in ("account_chart", "chart_of_accounts", "acct_chart", "account_codes"):
        _push(d)
    return found


def fetch_account_chart_detailed(client: Any) -> Tuple[List[Dict[str, Any]], str, str]:
    """
    讀取科目對照表。
    回傳 (rows, error_message, table_tried)：error_message 空字串表示至少有一表查詢成功（rows 可能仍為空）。
    """
    if client is None:
        return [], "無 Supabase client（未連線）", ""
    last_err = ""
    tried = ""
    for table in _account_chart_table_candidates():
        tried = table
        try:
            resp = client.table(table).select("*").execute()
            return list(resp.data or []), "", table
        except Exception as e:
            last_err = str(e)
            continue
    return [], last_err or "查無可用的科目對照表", tried


def fetch_account_chart(client: Any) -> List[Dict[str, Any]]:
    """讀取科目對照表；失敗時回傳空清單（詳見 fetch_account_chart_detailed）。"""
    rows, _, _ = fetch_account_chart_detailed(client)
    return rows


def fetch_user_company_prompt(client: Any, user: Dict[str, Any]) -> str:
    """讀取目前登入帳號＋公司統編對應之 user_companies.prompt。"""
    if client is None or not user:
        return ""
    u = str(user.get("username") or user.get("name") or "").strip()
    tax_n = str(user.get("verified_company_tax_id") or "").strip()
    if not u or not tax_n:
        return str(user.get("prompt") or "")
    binding = fetch_user_company_binding(client, u, tax_n)
    if binding:
        return str(binding.get("prompt") or "")
    return str(user.get("prompt") or "")


def update_user_company_prompt(client: Any, user: Dict[str, Any], prompt: str) -> bool:
    """
    將「預設 Prompt」寫回 user_companies（目前登入之帳號＋公司統編綁定列）。
    回傳 True 表示寫入成功；False 表示失敗（已在 UI 顯示錯誤）。
    """
    if client is None:
        st.error("尚未連線 Supabase，無法儲存。")
        return False
    if not user:
        st.error("請重新登入後再儲存預設 Prompt。")
        return False
    try:
        row_id = user.get("user_company_id")
        payload = {"prompt": str(prompt or "")}
        if row_id is not None:
            client.table("user_companies").update(payload).eq("id", row_id).execute()
            return True
        u = str(user.get("username") or user.get("name") or "").strip()
        tax_n = str(user.get("verified_company_tax_id") or "").strip()
        binding = fetch_user_company_binding(client, u, tax_n) if u and tax_n else None
        if not binding or binding.get("id") is None:
            st.error("找不到 user_companies 綁定資料，請重新登入並確認統編。")
            return False
        client.table("user_companies").update(payload).eq("id", binding["id"]).execute()
        return True
    except Exception as e:
        st.error(f"Supabase 更新 user_companies.prompt 失敗：{e}")
        return False


def update_user_prompt(client: Any, user_id: Any, prompt: str) -> bool:
    """已改為 user_companies；保留函式名稱供舊呼叫端，請改傳 user 字典。"""
    user = st.session_state.get("user") or {}
    if user_id is not None and user.get("id") is None:
        user = {**user, "id": user_id}
    return update_user_company_prompt(client, user, prompt)


# 寫入 Supabase invoices（送件年月 submission_yyymm；所屬期間由送件月推算，存於進項憑證明細）
SUPABASE_INVOICE_INSERT_KEYS = frozenset(
    {
        "submission_yyymm",
        "invoice_number",
        "invoice_type",
        "account",
        "buyer_tax_id",
        "buyer_name",
        "seller_tax_id",
        "seller_name",
        "transaction_date",
        "taxable_amount",
        "tax_amount",
        "total_amount",
        "description",
        "invoice_image_path",
        "system_status",
        "is_deductible",
        "user_name",
    }
)

# 寫入失敗時不可自動略過（須在 Supabase 建欄位）
INVOICE_INSERT_REQUIRED_COLUMNS = frozenset({"submission_yyymm"})


def invoice_period_columns_migration_sql() -> str:
    """Supabase SQL：建立送件年月欄位（與分析頁選擇一致）。"""
    return (
        "ALTER TABLE public.invoices ADD COLUMN IF NOT EXISTS submission_yyymm integer;"
    )


def _json_safe_scalar(value: Any) -> Any:
    """將 numpy / NaN 等轉成 PostgREST 可接受的純量。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        try:
            if value != value:  # NaN
                return None
        except Exception:
            pass
        return value
    if hasattr(value, "item"):
        try:
            return _json_safe_scalar(value.item())
        except Exception:
            pass
    return value


def _coerce_submission_yyymm(val: Any) -> Any:
    s = str(val or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    try:
        f = float(s.replace(",", ""))
        if f == int(f):
            return int(f)
    except (TypeError, ValueError):
        pass
    return None


def prepare_invoice_payload_for_supabase(
    row: Dict[str, Any],
    *,
    period: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    過濾並正規化寫入 Supabase 的欄位。
    送件年月／所屬期間優先取自 row，缺漏時由 period（分析頁選擇）補齊。
    """
    from utils.submission_period import SUBMISSION_YYYYMM_DB_COLUMN, period_row_fields

    base = dict(row or {})
    # 相容舊鍵名 submission_yyyymm → submission_yyymm
    if "submission_yyyymm" in base and SUBMISSION_YYYYMM_DB_COLUMN not in base:
        base[SUBMISSION_YYYYMM_DB_COLUMN] = base.get("submission_yyyymm")
    if period:
        for k, v in period_row_fields(period).items():
            if k not in base or base.get(k) in (None, ""):
                base[k] = v
        if not base.get(SUBMISSION_YYYYMM_DB_COLUMN):
            base[SUBMISSION_YYYYMM_DB_COLUMN] = period.get("submission_yyyymm")

    payload: Dict[str, Any] = {}
    for k, v in base.items():
        key = str(k).strip()
        if key == "submission_yyyymm":
            key = SUBMISSION_YYYYMM_DB_COLUMN
        if key not in SUPABASE_INVOICE_INSERT_KEYS:
            continue
        v = _json_safe_scalar(v)
        if key == SUBMISSION_YYYYMM_DB_COLUMN:
            v = _coerce_submission_yyymm(v)
            if v is None:
                continue
            payload[key] = v
            continue
        if key == "invoice_image_path" and v in ("", None):
            continue
        if v is None:
            continue
        payload[key] = v
    return payload


def _missing_column_from_postgrest_error(err: str) -> Optional[str]:
    m = re.search(r"Could not find the '([^']+)' column", err)
    return m.group(1) if m else None


def insert_invoice_to_supabase(
    client: Any,
    row: Dict[str, Any],
    *,
    period: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    將一筆新發票資料寫入 Supabase（含使用者選擇的送件年月 submission_yyymm）。
    非必要欄位在 PGRST204 時會自動略過；缺少 submission_yyymm 欄位時提示 migration SQL。
    """
    payload = prepare_invoice_payload_for_supabase(row, period=period)
    inv_no = str(payload.get("invoice_number") or "").strip()
    if not inv_no:
        st.error("Supabase 寫入失敗：發票號碼不可為空，請先完成辨識或手動填寫。")
        return False
    if not payload.get("submission_yyymm"):
        st.error(
            "Supabase 寫入失敗：缺少送件年月。請在「發票分析」頁選擇送件月份後再儲存。"
        )
        return False

    last_err = ""
    for _ in range(max(len(payload) + 2, 3)):
        if not payload:
            break
        try:
            client.table("invoices").insert(payload).execute()
            return True
        except Exception as e:
            last_err = str(e)
            col = _missing_column_from_postgrest_error(last_err)
            if col and col in payload:
                if col in INVOICE_INSERT_REQUIRED_COLUMNS:
                    break
                del payload[col]
                continue
            break

    err = last_err
    missing_col = _missing_column_from_postgrest_error(err)
    hint = ""
    if missing_col in INVOICE_INSERT_REQUIRED_COLUMNS:
        st.error(
            f"Supabase 寫入失敗：資料表缺少欄位「{missing_col}」（送件年月）。"
            "請在 Supabase SQL Editor 執行以下指令後再儲存："
        )
        st.code(invoice_period_columns_migration_sql(), language="sql")
        return False
    if "42501" in err or "row-level security" in err.lower():
        hint = (
            "（資料庫 RLS 拒絕寫入：請在 .streamlit/secrets.toml 設定 supabase.service_role_key，"
            "或於 Supabase 為 invoices 表新增 INSERT 政策）"
        )
    elif "PGRST204" in err or "Could not find the" in err:
        hint = "（資料表缺少欄位）"
    elif "duplicate key" in err.lower() or "23505" in err:
        hint = "（發票號碼可能已存在於資料庫）"
    label = f"發票 {inv_no}" if inv_no else "此筆"
    st.error(f"Supabase 寫入失敗（{label}）：{err}{hint}")
    return False


def filter_df_by_login_user(df: pd.DataFrame, username: str) -> pd.DataFrame:
    """
    依登入帳號篩選（user_name / 用戶代號）。
    若列上無使用者欄位或皆為空，仍保留（相容舊上傳僅有買方統編）。
    """
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    uname = str(username or "").strip()
    if not uname:
        return df.copy()
    user_cols = [c for c in ("user_name", "用戶代號") if c in df.columns]
    if not user_cols:
        return df.copy()

    def _row_ok(row: pd.Series) -> bool:
        vals = [str(row.get(c) or "").strip() for c in user_cols]
        if all(not v or v.lower() in ("nan", "none", "nat") for v in vals):
            return True
        return any(v == uname for v in vals)

    mask = df.apply(_row_ok, axis=1)
    return df.loc[mask].copy()


def filter_df_by_buyer_tax_id(df: pd.DataFrame, buyer_tax_id: str) -> pd.DataFrame:
    """依買方統編篩選（支援 buyer_tax_id / 買方統編 欄位）。"""
    from utils.invoice_fmt import normalize_buyer_tax_id

    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    tid = normalize_buyer_tax_id(buyer_tax_id)
    if not tid:
        return df.copy()
    has_buyer_col = any(c in df.columns for c in ("buyer_tax_id", "買方統編"))
    if not has_buyer_col:
        return df.copy()
    for col in ("buyer_tax_id", "買方統編"):
        if col not in df.columns:
            continue
        norm = df[col].map(lambda x: normalize_buyer_tax_id(x))
        return df.loc[norm == tid].copy()
    return df.iloc[0:0].copy()


def fetch_input_voucher_details_from_supabase(
    client: Any,
    buyer_tax_id: Optional[str] = None,
    user_name: Optional[str] = None,
) -> pd.DataFrame:
    """
    自「進項憑證明細」讀取資料。
    可選依買方統編、登入帳號（user_name／用戶代號）篩選。
    """
    if client is None:
        return pd.DataFrame()
    tbl = input_voucher_detail_table_name()
    try:
        resp = client.table(tbl).select("*").execute()
        df = pd.DataFrame(resp.data or [])
    except Exception as e:
        st.warning(f"讀取「{tbl}」失敗：{e}")
        return pd.DataFrame()
    tid = str(buyer_tax_id or "").strip()
    if tid:
        df = filter_df_by_buyer_tax_id(df, tid)
    uname = str(user_name or "").strip()
    if uname:
        df = filter_df_by_login_user(df, uname)
    return df


def input_voucher_detail_table_name() -> str:
    """
    進項憑證明細表名（與 PostgREST 暴露的表名一致）。
    可於環境變數 INPUT_VOUCHER_DETAIL_TABLE 或 secrets INPUT_VOUCHER_DETAIL_TABLE 覆寫。
    """
    try:
        tv = str(st.secrets.get("INPUT_VOUCHER_DETAIL_TABLE") or "").strip()
    except Exception:
        tv = ""
    if not tv:
        tv = str(os.environ.get("INPUT_VOUCHER_DETAIL_TABLE") or "").strip()
    return tv or "進項憑證明細"


def _cell_for_postgres_insert(val: Any) -> Any:
    """
    將 DataFrame 儲存格轉成 PostgREST 可接受的值。
    - NaN / 空字串 / 僅空白 → None（避免 integer 欄位收到 '' 觸發 22P02）
    - numpy 純量 → 以 .item() 遞迴轉成 Python 原生型別
    """
    if val is None:
        return None
    try:
        if not isinstance(val, (str, bytes)) and pd.isna(val):
            return None
    except Exception:
        pass
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        try:
            f = float(s.replace(",", ""))
            if f == int(f):
                return int(f)
        except (TypeError, ValueError):
            pass
        return s
    if isinstance(val, (bool, int)):
        return val
    if isinstance(val, float):
        if pd.isna(val):
            return None
        if val == int(val):
            return int(val)
        return val
    if hasattr(val, "item") and not isinstance(val, (str, bytes)):
        try:
            return _cell_for_postgres_insert(val.item())
        except Exception:
            return val
    return val


def _dataframe_rows_for_supabase(
    df: pd.DataFrame,
    *,
    integer_columns: Optional[frozenset[str]] = None,
) -> List[Dict[str, Any]]:
    """將 DataFrame 列轉成可 JSON 序列化之 dict（NaN、空字串 → None）。"""
    from utils.invoice_export import coerce_voucher_integer

    int_cols = integer_columns or frozenset()
    records: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        d: Dict[str, Any] = {}
        for col in df.columns:
            key = str(col).strip()
            raw = row[col]
            if key in int_cols:
                d[key] = coerce_voucher_integer(raw)
            else:
                d[key] = _cell_for_postgres_insert(raw)
        records.append(d)
    return records


def _normalize_voucher_column_name(name: str) -> str:
    return (
        str(name or "")
        .strip()
        .replace("（", "(")
        .replace("）", ")")
    )


def _finalize_voucher_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """寫入前再次整數化，避免編輯器殘留 \"5.0\" 字串。"""
    from utils.invoice_export import INPUT_VOUCHER_INTEGER_COLUMNS, coerce_voucher_integer

    int_keys = {_normalize_voucher_column_name(c) for c in INPUT_VOUCHER_INTEGER_COLUMNS}
    out: List[Dict[str, Any]] = []
    for rec in records or []:
        row: Dict[str, Any] = {}
        for k, v in (rec or {}).items():
            key = str(k).strip()
            norm = _normalize_voucher_column_name(key)
            if norm in int_keys:
                row[key] = coerce_voucher_integer(v)
            else:
                row[key] = _cell_for_postgres_insert(v)
        out.append(row)
    return out


def prepare_input_voucher_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    僅保留「進項憑證明細」表存在的欄位。
    買方統編使用中文欄名「買方統編」，勿傳 buyer_tax_id（DB 無此欄）。
    integer 欄位會將 5.0 / "5.0" 轉成 5，避免 Postgres 22P02。
    """
    from utils.invoice_export import (
        coerce_voucher_integer,
        input_voucher_insert_column_names,
        INPUT_VOUCHER_INTEGER_COLUMNS,
    )

    if df is None or df.empty:
        return pd.DataFrame()
    allowed = input_voucher_insert_column_names()
    cols = [c for c in df.columns if str(c).strip() in allowed]
    out = df[cols].copy() if cols else pd.DataFrame()
    if "買方統編" not in out.columns and "buyer_tax_id" in df.columns:
        out["買方統編"] = df["buyer_tax_id"]
    col_by_key = {_normalize_voucher_column_name(c): c for c in out.columns}
    for int_name in INPUT_VOUCHER_INTEGER_COLUMNS:
        src = col_by_key.get(_normalize_voucher_column_name(int_name))
        if src is not None:
            out[src] = out[src].map(coerce_voucher_integer)
    return out


def insert_input_voucher_details_from_dataframe(
    client: Any,
    df: pd.DataFrame,
    *,
    table_name: Optional[str] = None,
    batch_size: int = 120,
) -> Tuple[int, str]:
    """
    將「進項匯出格式」DataFrame 寫入 Supabase 指定表（預設：進項憑證明細）。
    欄名須與資料表欄位一致（建議與 invoice_export.EXPORT_COLUMNS 對齊）。
    回傳 (成功寫入筆數, 錯誤訊息)；成功時錯誤訊息為空字串。
    """
    if client is None:
        return 0, "無 Supabase 連線。"
    if df is None or df.empty:
        return 0, "沒有資料可上傳。"
    tbl = (table_name or input_voucher_detail_table_name()).strip()
    if not tbl:
        return 0, "未設定目標表名。"
    df = prepare_input_voucher_dataframe(df)
    if df.empty:
        return 0, "沒有符合資料表欄位的資料可上傳。"
    from utils.invoice_export import INPUT_VOUCHER_INTEGER_COLUMNS

    records = _finalize_voucher_records(
        _dataframe_rows_for_supabase(df, integer_columns=INPUT_VOUCHER_INTEGER_COLUMNS)
    )
    if not records:
        return 0, "沒有有效列。"
    n_ok = 0
    try:
        for i in range(0, len(records), max(1, int(batch_size))):
            chunk = records[i : i + max(1, int(batch_size))]
            client.table(tbl).insert(chunk).execute()
            n_ok += len(chunk)
        return n_ok, ""
    except Exception as e:
        err = str(e)
        if "PGRST204" in err or "Could not find the" in err:
            err += "（請確認「進項憑證明細」欄位與匯出欄位一致；買方統編請用「買方統編」而非 buyer_tax_id）"
        return n_ok, err


def delete_invoices_by_invoice_numbers(client: Any, numbers: List[str]) -> Tuple[int, str]:
    """
    自 public.invoices 刪除 invoice_number 與清單相符的列（號碼會先經 normalize_invoice_number）。
    用於進項憑證上傳後避免重複上傳同一張發票。
    回傳 (送出的刪除請求筆數（去重後號碼數）, 錯誤訊息)；成功時錯誤訊息為空字串。
    """
    from utils.invoice_fmt import normalize_invoice_number

    if client is None:
        return 0, "無 Supabase 連線。"
    nums = list(
        dict.fromkeys(
            normalize_invoice_number(str(x or "")) for x in (numbers or []) if str(x or "").strip()
        )
    )
    nums = [n for n in nums if n]
    if not nums:
        return 0, ""
    batch = 80
    try:
        for i in range(0, len(nums), batch):
            chunk = nums[i : i + batch]
            client.table("invoices").delete().in_("invoice_number", chunk).execute()
        return len(nums), ""
    except Exception as e:
        return 0, str(e)

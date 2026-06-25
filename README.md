# 發票掃描與辨識（Supabase 版）

使用 **Gemini Vision（可設定 `GEMINI_MODEL`，預設 `models/gemini-3-flash-preview`）** 讀取發票圖片內容，自動擷取欄位，並提供 **Streamlit** 網頁介面讓你一次上傳多張發票圖片、檢視/修正資料，最後把結果 **寫入 Supabase（invoices 表）**。

本專案主要使用偏「會計系統」風格的 Streamlit App（`accounting/app.py`）：

- 可一次上傳多張發票圖片
- 逐張進行 Gemini 欄位擷取
- 右側可切換查看每張結果
- **一鍵將多張發票寫入 Supabase（invoices 表）**

## 功能

- **多檔上傳**：一次上傳多張發票圖片
- **AI 擷取欄位**：從圖片擷取欄位並整理成結構化資料
- **前端可編修**：可在 UI 中直接修改欄位後再存
- **模型除錯**：可用 ListModels 列出可用模型，避免 404 model not found
- **Supabase 寫入**：支援單筆/批次寫入 `invoices`（需設定 secrets + RLS 對策）

## 專案結構

```
.
├─ accounting/
│  ├─ app.py                      # 會計系統風格 Streamlit 入口（Supabase）
│  ├─ views/analyze.py            # 上傳多張→Gemini 擷取→一鍵批次寫入 DB
│  ├─ utils/database.py           # Supabase client / 讀寫 invoices
│  ├─ services/llm_service.py      # Gemini Vision 擷取與欄位整理
│  └─ .streamlit/secrets.toml     # Supabase URL / keys（請勿提交）
├─ requirements.txt
├─ APITest.py                     # 列出可用模型（generateContent）
```

## 環境需求

- Python 3.10+（建議 3.11/3.12）

## 安裝與啟動（Windows / PowerShell）

在專案根目錄執行。

### 1) 建立虛擬環境（建議）

```powershell
python -m venv venv
```

> 你的 PowerShell 可能因 Execution Policy 不能執行 `venv\Scripts\Activate.ps1`。
> 沒關係，以下指令都直接用 `venv\Scripts\python`，不需要 activate。

### 2) 安裝依賴

```powershell
.\venv\Scripts\python -m pip install -r requirements.txt
```

### 3) 設定 LLM API Key（建議用系統設定頁）

- **建議做法**：啟動後到「系統設定 → LLM API Keys」儲存 Google key（會寫入本機 `accounting/user_prefs.json`）。
- API Key 取得：`https://aistudio.google.com/apikey`

### 4) 啟動 Streamlit

#### Supabase 版（accounting app）

```powershell
.\venv\Scripts\python -m streamlit run accounting\app.py
```

> 模型名稱可用環境變數 `GEMINI_MODEL` 覆蓋（選用）；API Key 預設由「系統設定」保存的 `user_prefs.json` 讀取。

## 使用流程

### Supabase 版（`accounting/app.py`）

1. 登入後進入 **發票分析**
2. 上傳發票圖片（可多選）
3. 選 **Google · gemini-flash** 後點 **「一鍵分析」**
4. 右側用下拉切換查看每張發票結果
5. 到 **操作** 分頁：
   - 點 **「儲存目前這張」**：只存目前選中的那一張
   - 點 **「全部儲存至資料庫」**：一鍵把本次多張發票全部寫入 Supabase（invoices 表）

## 模型 / 404 排查（很常見）

### 1) 看到 `404 models/... not found` 怎麼辦？

代表 **模型名稱不在你這把 API key 可用清單**。請用其中一種方式列出可用模型：

- Streamlit 左側點 **「列出可用模型（ListModels）」**
- 或跑：

```powershell
.\venv\Scripts\python APITest.py
```

把 `.env` 的 `GEMINI_MODEL` 改成清單裡支援 `generateContent` 的模型名稱，例如：

- `models/gemini-3-flash-preview`
- `models/gemini-3-pro-preview`
- `models/gemini-3-pro-image-preview`

改完後 **重啟 Streamlit**。

### 2) 為什麼看起來「沒有讀到發票資訊」？

當 Gemini 回覆不是純 JSON、或 API 失敗時，系統會顯示「擷取失敗原因」的可展開區塊（你可以看到真正錯誤原因），並仍然讓你在表格中手動補值。

## Supabase / RLS 常見問題（accounting app）

### 1) `new row violates row-level security policy for table "invoices"`

代表 `invoices` 表啟用 RLS，而你用的是 anon key，預設無法 insert。

**快速解法（方案 A）**：在 `accounting/.streamlit/secrets.toml` 加入 `service_role_key`，並重啟 Streamlit。

範例（請自行貼上你的 key）：

```toml
[supabase]
url = "https://YOUR_PROJECT.supabase.co"
key = "YOUR_ANON_KEY"
service_role_key = "YOUR_SERVICE_ROLE_KEY"
```

> `service_role_key` 權限極高，請勿放到前端、請勿提交到 Git、僅限可信任環境使用。
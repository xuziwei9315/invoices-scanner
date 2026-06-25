import streamlit as st
import pandas as pd
import random
from datetime import date, datetime

from utils.layout import header, card
from utils.auth import touch_auth_session
from utils.database import (
    fetch_invoices_from_supabase,
    fetch_user_company_binding,
    fetch_user_company_prompt,
    get_supabase_config,
    update_user_company_prompt,
)
from utils.data_tools import df_to_excel_bytes
from utils.invoice_export import invoices_to_export_dataframe
from utils.account_chart import invalidate_account_chart_cache
from utils.prefs import load_llm_api_keys, save_llm_api_key_for


def _render_cloud_ops_compact(sb) -> None:
    """雲端連線診斷、資料同步、系統狀態（精簡橫列）。"""
    secrets_ok = False
    secrets_src = ""
    try:
        cfg = get_supabase_config()
        secrets_ok = bool(cfg.get("url")) and bool(cfg.get("key"))
        secrets_src = str(cfg.get("source") or "")
    except Exception:
        secrets_ok = False
        secrets_src = ""

    api_ok = False
    api_err = ""
    if sb:
        try:
            sb.table("invoices").select("id").limit(1).execute()
            api_ok = True
        except Exception as e:
            api_err = str(e)

    src = st.session_state.get("data_source", "unknown")
    sync_ok = src == "supabase"
    s = st.session_state.get("ai_status") or {}
    ai_running = bool(s.get("running"))
    latency = int(s.get("latency_ms") or 0)

    def _badge(ok: bool, ok_txt: str, fail_txt: str) -> str:
        dot = "dot-green" if ok else "dot-red"
        return f"<span class='badge badge-sm'><span class='dot {dot}'></span>{ok_txt if ok else fail_txt}</span>"

    src_label = {
        "streamlit_secrets": "secrets",
        "accounting_secrets_toml": "toml",
        "env": "env",
    }.get(secrets_src, secrets_src or "—")

    with card():
        st.markdown(
            "<div class='section-title cloud-ops-title'>雲端與系統</div>",
            unsafe_allow_html=True,
        )
        c_diag, c_sync, c_status, c_actions = st.columns([1.1, 1, 1.15, 0.85], gap="small")

        with c_diag:
            st.markdown("<div class='cloud-ops-label'>連線診斷</div>", unsafe_allow_html=True)
            st.markdown(
                _badge(secrets_ok, f"設定 OK ({src_label})", "設定缺失"),
                unsafe_allow_html=True,
            )
            st.markdown(
                _badge(sb and api_ok, "API 正常", "API 失敗" if sb else "未連線"),
                unsafe_allow_html=True,
            )
            if (sb and not api_ok) and api_err:
                st.caption(api_err[:80] + ("…" if len(api_err) > 80 else ""))

        with c_sync:
            st.markdown("<div class='cloud-ops-label'>資料同步</div>", unsafe_allow_html=True)
            st.markdown(
                _badge(sync_ok, "Supabase", str(src)),
                unsafe_allow_html=True,
            )
            inv_df_cache = st.session_state.get("invoices")
            if isinstance(inv_df_cache, pd.DataFrame):
                inv_n = len(inv_df_cache)
            elif inv_df_cache is None:
                inv_n = 0
            else:
                inv_n = len(inv_df_cache)
            st.caption(f"本機快取 {inv_n} 筆")

        with c_status:
            st.markdown("<div class='cloud-ops-label'>系統狀態</div>", unsafe_allow_html=True)
            st.markdown(
                _badge(ai_running, "AI 運行中", "AI 停止"),
                unsafe_allow_html=True,
            )
            st.caption(f"P95 {latency} ms · {s.get('updated_at', '—')}")

        with c_actions:
            st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
            if st.button("同步", use_container_width=True, icon=":material/sync:", key="settings_sync"):
                if sb:
                    df_fresh = fetch_invoices_from_supabase(sb)
                    if not df_fresh.empty:
                        st.session_state["invoices"] = df_fresh
                        st.session_state["data_source"] = "supabase"
                        invalidate_account_chart_cache()
                        st.success(f"已同步 {len(df_fresh)} 筆")
                        st.rerun()
                    st.error("資料庫回傳空值。")
                else:
                    st.error("無法連線。")
            if st.button("刷新狀態", use_container_width=True, icon=":material/refresh:", key="settings_refresh_status"):
                rng = random.Random(2026)
                st.session_state.setdefault("ai_status", {})
                st.session_state["ai_status"]["latency_ms"] = max(420, int(rng.gauss(820, 120)))
                st.session_state["ai_status"]["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                st.rerun()
            inv_df = st.session_state.get("invoices")
            if isinstance(inv_df, pd.DataFrame) and not inv_df.empty:
                excel_data = df_to_excel_bytes(
                    invoices_to_export_dataframe(
                        inv_df,
                        st.session_state.get("user") or {},
                    ),
                    sheet_name="進項憑證",
                )
                st.download_button(
                    "匯出",
                    data=excel_data,
                    file_name=f"invoices_{date.today()}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key="settings_export_xls",
                )


def render_settings():
    header("系統設定", "管理 LLM 金鑰、預設 Prompt 與雲端連線。")

    sb = st.session_state.get("supabase")

    c_keys, c_prefs = st.columns([1, 1], gap="large")

    with c_keys:
        with card():
            st.markdown("<div class='section-title'>LLM API Keys</div>", unsafe_allow_html=True)
            st.markdown(
                "<div class='muted'>儲存在本機 <span class='mono'>user_prefs.json</span>。</div>",
                unsafe_allow_html=True,
            )

            user = st.session_state.get("user") or {}
            keys = load_llm_api_keys(user) if user else {}
            st.session_state["llm_api_keys"] = keys

            tabs = st.tabs(["OpenAI", "Anthropic", "Google"])

            def _render_key_tab(llm_id: str, label: str, placeholder: str):
                current_key = st.session_state.get("llm_api_keys", {}).get(llm_id, "")
                v = st.text_input(
                    f"{label} API Key",
                    value=current_key,
                    type="password",
                    placeholder=placeholder,
                    key=f"api_key_{llm_id}",
                )
                if st.button(
                    "儲存",
                    type="primary",
                    use_container_width=True,
                    icon=":material/save:",
                    key=f"save_{llm_id}",
                ):
                    save_llm_api_key_for(user, llm_id, v)
                    st.session_state.setdefault("llm_api_keys", {})
                    st.session_state["llm_api_keys"][llm_id] = v
                    if st.session_state.get("active_llm_id") == llm_id:
                        st.session_state["llm_api_key"] = v
                    st.success("已儲存。")

            with tabs[0]:
                _render_key_tab("openai", "OpenAI", "sk-...")
            with tabs[1]:
                _render_key_tab("anthropic", "Anthropic", "sk-ant-...")
            with tabs[2]:
                _render_key_tab("google", "Google", "AIza...")

    with c_prefs:
        with card():
            st.markdown("<div class='section-title'>預設 Prompt</div>", unsafe_allow_html=True)
            st.markdown(
                "<div class='muted'>儲存於 Supabase <span class='mono'>user_companies.prompt</span>"
                "（目前登入帳號與公司統編之綁定列），會帶入「發票分析」頁面。</div>",
                unsafe_allow_html=True,
            )

            user = st.session_state.get("user") or {}
            if sb is not None and user:
                current_prompt = fetch_user_company_prompt(sb, user)
            else:
                current_prompt = str(user.get("prompt", "") or "")

            new_prompt = st.text_area(
                "預設 Prompt 內容",
                value=current_prompt,
                height=280,
                key="settings_default_prompt",
                placeholder="請辨識發票並判斷扣抵性…",
            )

            b1, b2 = st.columns([1, 1], gap="medium")
            with b1:
                if st.button(
                    "儲存預設 Prompt",
                    type="primary",
                    use_container_width=True,
                    icon=":material/save:",
                    disabled=(sb is None or not user),
                ):
                    if sb is None:
                        st.error("尚未連線 Supabase。")
                    elif not user:
                        st.error("請重新登入。")
                    else:
                        ok = update_user_company_prompt(sb, user, new_prompt)
                        if ok:
                            uid = user.get("user_company_id")
                            if uid is None:
                                b = fetch_user_company_binding(
                                    sb,
                                    str(user.get("username") or user.get("name") or ""),
                                    str(user.get("verified_company_tax_id") or ""),
                                )
                                uid = b.get("id") if b else None
                            st.session_state["user"] = {
                                **user,
                                "prompt": new_prompt,
                                "user_company_id": uid,
                            }
                            touch_auth_session()
                            st.success("已儲存。")
                            st.rerun()
            with b2:
                if st.button(
                    "清空為預設值",
                    use_container_width=True,
                    icon=":material/restart_alt:",
                    disabled=(sb is None or not user),
                ):
                    if sb and user:
                        ok = update_user_company_prompt(sb, user, "")
                        if ok:
                            st.session_state["user"] = {**user, "prompt": ""}
                            touch_auth_session()
                            st.success("已清空。")
                            st.rerun()

    st.markdown("")
    _render_cloud_ops_compact(sb)

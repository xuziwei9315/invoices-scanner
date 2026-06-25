import streamlit as st

# 顏色定義 (Token)
PRIMARY   = "#2F5D8C"
SECONDARY = "#6B8CA3"
BG        = "#F5F7FA"
ALERT     = "#F04438"

def inject_css():
    theme = st.session_state.get("theme") or {}
    primary = theme.get("primary", PRIMARY)
    secondary = theme.get("secondary", SECONDARY)
    bg = theme.get("bg", BG)
    alert = theme.get("alert", ALERT)

    st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=Noto+Sans+TC:wght@400;500;600;700;800;900&display=swap');

/* ── design tokens ── */
:root {{
  --c-bg:       {bg};
  --c-primary:  {primary};
  --c-secondary:{secondary};
  --c-alert:    {alert};
  --c-text:     #0F1A24;
  --c-muted:    rgba(15,26,36,.62);
  --c-border:   rgba(47,93,140,.16);
  --sidebar-w:  276px;

  /* ── RWD fluid typography ── */
  --fs-h1:    clamp(1.35rem, 1.8vw + .5rem, 1.875rem);   /* ~22–30 px */
  --fs-h2:    clamp(1rem,    1.1vw + .35rem, 1.25rem);   /* ~16–20 px */
  --fs-body:  clamp(.8125rem, .55vw + .5rem, .9375rem);  /* ~13–15 px */
  --fs-sm:    clamp(.75rem,  .4vw  + .46rem, .8125rem);  /* ~12–13 px */
  --fs-kpi:   clamp(1.625rem,2vw   + .3rem,  2.375rem);  /* ~26–38 px */
  --fs-kpi22: clamp(1.1rem,  1.4vw + .2rem,  1.5rem);    /* ~18–24 px */
}}

/* ── base reset ── */
html, body, [class*="css"] {{
  font-family: Inter, "Noto Sans TC", system-ui, "PingFang TC",
               "Microsoft JhengHei", sans-serif;
  font-size: var(--fs-body);
  color: var(--c-text);
  -webkit-font-smoothing: antialiased;
}}

.stApp {{ background: var(--c-bg); }}

/* ── remove Streamlit top chrome (avoid overlay) ── */
header[data-testid="stHeader"] {{
  height: 0 !important;
  min-height: 0 !important;
  border: 0 !important;
}}
div[data-testid="stDecoration"] {{
  display: none !important;
}}

/* Auth 用隱藏 iframe（分頁同步／閒置登出腳本），不佔主內容版面 */
.main [data-testid="stElementContainer"]:has(iframe) {{
  height: 0 !important;
  min-height: 0 !important;
  margin: 0 !important;
  padding: 0 !important;
  overflow: hidden !important;
  line-height: 0 !important;
}}
.main iframe {{
  display: block !important;
  width: 0 !important;
  height: 0 !important;
  min-height: 0 !important;
  margin: 0 !important;
  padding: 0 !important;
  border: 0 !important;
  overflow: hidden !important;
  visibility: hidden !important;
  position: absolute !important;
  pointer-events: none !important;
}}

.block-container {{
  padding-top: 1.5rem;
  padding-bottom: 1.5rem;
  max-width: 1300px;
}}

/* ── universal "card" styling for bordered containers ── */
div[data-testid="stVerticalBlockBorderWrapper"] {{
  border-radius: 16px;
  border: 1px solid rgba(47,93,140,.14) !important;
  background: rgba(255,255,255,.98);
  box-shadow: 0 12px 28px rgba(15,26,36,.08);
}}
div[data-testid="stVerticalBlockBorderWrapper"] > div {{
  padding: 14px 16px;
}}

/* ── report center: tinted cards (use :has marker) ── */
div[data-testid="stVerticalBlockBorderWrapper"]:has(.report-card-marker.report-financial) {{
  background: rgba(37, 99, 235, .08) !important;
  border-color: rgba(37, 99, 235, .18) !important;
}}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.report-card-marker.report-tax) {{
  background: rgba(22, 163, 74, .08) !important;
  border-color: rgba(22, 163, 74, .18) !important;
}}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.report-card-marker.report-invoice) {{
  background: rgba(249, 115, 22, .08) !important;
  border-color: rgba(249, 115, 22, .18) !important;
}}
.report-card-marker {{
  height: 0;
  width: 0;
  overflow: hidden;
}}

/* ── analyze: submission period section ── */
.submission-period-section {{
  margin-bottom: 10px;
}}
.submission-period-head {{
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px 20px;
  flex-wrap: wrap;
}}
.submission-period-head-title {{
  font-size: var(--fs-h2);
  font-weight: 700;
  color: #334155;
  display: flex;
  align-items: center;
  gap: 10px;
  line-height: 1.25;
}}
.submission-period-head-title::before {{
  content: "";
  display: inline-block;
  width: 4px;
  height: 1.15em;
  border-radius: 3px;
  background: linear-gradient(180deg, #2F80ED 0%, var(--c-primary) 100%);
  flex-shrink: 0;
}}
.submission-period-head-hint {{
  font-size: var(--fs-sm);
  color: var(--c-muted);
  line-height: 1.45;
  max-width: 52rem;
}}

.submission-period-bar-marker,
.submission-pick-zone-marker,
.submission-out-zone-marker {{
  height: 0;
  width: 0;
  overflow: hidden;
}}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.submission-period-bar-marker) {{
  background: linear-gradient(
    105deg,
    rgba(47, 128, 237, .09) 0%,
    rgba(255, 255, 255, .98) 38%,
    rgba(47, 93, 140, .04) 100%
  ) !important;
  border-color: rgba(47, 128, 237, .22) !important;
  box-shadow: 0 8px 24px rgba(47, 93, 140, .10) !important;
  position: relative;
  overflow: hidden;
}}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.submission-period-bar-marker)::before {{
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, #2F80ED, var(--c-primary));
  opacity: .85;
  pointer-events: none;
}}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.submission-period-bar-marker) > div {{
  padding: 14px 18px !important;
}}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.submission-period-bar-marker) [data-testid="column"] {{
  align-self: center;
}}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.submission-period-bar-marker)
  [data-testid="column"]:has(.submission-pick-zone-marker) {{
  background: rgba(255, 255, 255, .72);
  border: 1px solid rgba(47, 93, 140, .14);
  border-radius: 12px;
  padding: 10px 12px 6px !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .9);
}}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.submission-period-bar-marker)
  [data-testid="column"]:has(.submission-out-zone-marker) {{
  background: rgba(47, 128, 237, .05);
  border: 1px dashed rgba(47, 128, 237, .22);
  border-radius: 12px;
  padding: 10px 12px 8px !important;
}}

.submission-zone-label {{
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .06em;
  text-transform: uppercase;
  color: rgba(47, 93, 140, .72);
  margin-bottom: 6px;
}}
.submission-flow-arrow {{
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  margin: 0 auto;
  border-radius: 999px;
  background: rgba(47, 128, 237, .12);
  border: 1px solid rgba(47, 128, 237, .22);
  color: var(--c-primary);
  font-size: 1.1rem;
  font-weight: 700;
  line-height: 1;
  box-shadow: 0 2px 8px rgba(47, 128, 237, .12);
}}

div[data-testid="stVerticalBlockBorderWrapper"]:has(.submission-period-bar-marker) [data-testid="stSelectbox"] label {{
  font-size: var(--fs-sm) !important;
  font-weight: 600 !important;
  color: rgba(15, 26, 36, .72) !important;
  margin-bottom: 4px !important;
}}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.submission-period-bar-marker) [data-testid="stSelectbox"] div[role="combobox"] {{
  min-height: 38px;
  font-weight: 600;
}}

.period-pill {{
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 14px;
  border-radius: 12px;
  background: rgba(47, 93, 140, .06);
  border: 1px solid rgba(47, 93, 140, .12);
  min-width: 0;
  height: 100%;
  box-shadow: 0 1px 2px rgba(15, 26, 36, .04);
}}
.period-pill .label {{
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .04em;
  color: var(--c-muted);
  line-height: 1.2;
}}
.period-pill .value {{
  font-family: ui-monospace, "Cascadia Mono", Consolas, monospace;
  font-size: clamp(.9rem, .5vw + .7rem, 1rem);
  font-weight: 700;
  color: var(--c-text);
  white-space: nowrap;
  letter-spacing: .02em;
}}
.period-pill-primary {{
  background: linear-gradient(135deg, rgba(47, 128, 237, .12), rgba(255, 255, 255, .9)) !important;
  border-color: rgba(47, 128, 237, .26) !important;
}}
.period-pill-primary .value {{
  color: var(--c-primary);
}}
.period-pill-accent {{
  background: linear-gradient(135deg, rgba(47, 128, 237, .20), rgba(47, 128, 237, .10)) !important;
  border-color: rgba(47, 128, 237, .34) !important;
  box-shadow: 0 4px 12px rgba(47, 128, 237, .12);
}}
.period-pill-accent .value {{
  color: #1d4ed8;
}}
.period-pill-accent .label {{
  color: rgba(29, 78, 216, .75);
}}

@media (max-width: 900px) {{
  .submission-period-head {{
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
  }}
  .submission-flow-arrow {{
    transform: rotate(90deg);
    margin: 4px auto;
  }}
}}

/* ── inputs: subtle light-blue background for readability ── */
div[data-testid="stTextInput"] input,
div[data-testid="stNumberInput"] input,
div[data-testid="stDateInput"] input,
div[data-testid="stTextArea"] textarea,
div[data-testid="stSelectbox"] div[role="combobox"] {{
  background: rgba(47, 128, 237, .06) !important;
  border: 1px solid rgba(47, 128, 237, .18) !important;
  border-radius: 10px !important;
}}

div[data-testid="stTextInput"] input:focus,
div[data-testid="stNumberInput"] input:focus,
div[data-testid="stDateInput"] input:focus,
div[data-testid="stTextArea"] textarea:focus,
div[data-testid="stSelectbox"] div[role="combobox"]:focus-within {{
  box-shadow: 0 0 0 3px rgba(47, 128, 237, .16) !important;
}}

/* ── dataframe: allow horizontal scroll ── */
div[data-testid="stDataFrame"] {{
  overflow-x: auto;
}}

/* ── typography helpers ── */
.h1  {{ font-size: var(--fs-h1);  font-weight: 800; letter-spacing: .2px; line-height: 1.2; }}
.h2  {{ font-size: var(--fs-h2);  font-weight: 700; line-height: 1.25; }}
.sub {{ font-size: var(--fs-sm);  color: var(--c-muted); margin-top: 4px; }}
.muted {{ color: var(--c-muted); font-size: var(--fs-sm); }}
.mono {{
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco,
               Consolas, "Liberation Mono", "Courier New", monospace;
  font-variant-numeric: tabular-nums;
}}

.content-section {{
    padding: 30px 0;
    border-bottom: 1px solid #F1F5F9;
}}

/* 讓標題更有呼吸感 */
.h1 {{ font-size: 2rem; font-weight: 800; margin-bottom: 0.5rem; color: #1E293B; }}
.h2 {{ font-size: 1.25rem; font-weight: 700; margin-bottom: 1.5rem; color: #334155; }}

/* 強化側邊欄：不再像是一個抽屜，更像一個導航面板 */
[data-testid="stSidebar"] {{
    background-color: #F8FAFC !important;
    border-right: 1px solid #E2E8F0 !important;
}}

/* 讓按鈕看起來更現代：去除生硬邊框 */
div.stButton > button {{
    border-radius: 8px;
    border: none;
    box-shadow: 0 3px 5px rgba(0,0,0,0.1);
    background-color: white;
}}

/* 強調主要按鈕 */
div.stButton > button[kind="primary"] {{
    background: linear-gradient(135deg, #2563EB, #1D4ED8);
    color: white;
}}

/* ── section title inside card ── */
.section-title {{
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  font-size: var(--fs-h2);
  font-weight: 700;
  color: var(--c-text);
}}

/* ── KPI ── */
.kpi-title {{ font-size: var(--fs-sm);  color: var(--c-muted); font-weight: 500; }}
.kpi-value {{ font-size: var(--fs-kpi); font-weight: 800; margin-top: 6px; line-height: 1.15; color: var(--c-text); }}
.kpi-hint  {{ font-size: var(--fs-sm);  color: var(--c-muted); margin-top: 6px; }}

/* KPI tiles: for single-markdown blocks (can have per-tile backgrounds) */
.kpi-tile {{
  border-radius: 16px;
  border: 1px solid rgba(47,93,140,.14);
  box-shadow: 0 12px 28px rgba(15,26,36,.08);
  padding: 14px 16px;
  min-height: 120px;
}}
.kpi-tile-1 {{ background: rgba(37, 99, 235, .08); }}
.kpi-tile-2 {{ background: rgba(22, 163,  74, .08); }}
.kpi-tile-3 {{ background: rgba(249, 115,  22, .10); }}
.kpi-tile-4 {{ background: rgba(139,  92, 246, .09); }}

/* ── settings: compact cloud ops strip ── */
.cloud-ops-title {{
  font-size: var(--fs-md) !important;
  margin-bottom: 8px !important;
}}
.cloud-ops-label {{
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--c-muted);
  margin-bottom: 6px;
}}
.badge-sm {{
  font-size: 11px !important;
  padding: 4px 8px !important;
  margin: 2px 4px 2px 0;
  display: inline-block;
}}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.cloud-ops-title) {{
  padding-top: 10px !important;
  padding-bottom: 10px !important;
}}

/* ── status metric ── */
.status-metric {{
  border-radius: 12px;
  background: rgba(245,247,250,.96);
  padding: 10px 14px;
  border: 1px solid rgba(47,93,140,.10);
  margin-top: 10px;
  font-size: var(--fs-sm);
  color: var(--c-muted);
}}
.status-metric .mono {{
  font-size: var(--fs-kpi22);
  font-weight: 900;
  margin-top: 4px;
  color: var(--c-text);
}}
.status-metric .ts {{
  font-size: var(--fs-sm);
  margin-top: 4px;
  color: var(--c-text);
}}

/* ── alert list ── */
.alert-list {{ display: grid; gap: 10px; }}
.alert-item {{
  border-radius: 12px;
  padding: 12px 14px;
  border: 1px solid rgba(240,68,56,.18);
  background: rgba(240,68,56,.06);
  font-size: var(--fs-sm);
  color: var(--c-text);
}}
.alert-item strong {{
  color: var(--c-alert);
  display: block;
  margin-bottom: 4px;
  font-size: var(--fs-sm);
}}
.risk-compact .alert-item {{
  padding: 10px 12px;
  line-height: 1.35;
}}
.risk-compact .alert-item strong {{
  margin-bottom: 2px;
}}

/* ── badge / dot ── */
.badge {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 999px;
  font-size: var(--fs-sm);
  font-weight: 700;
  border: 1px solid rgba(47,93,140,.18);
  background: rgba(238,243,248,.9);
  color: var(--c-text);
}}
.dot {{ width: 8px; height: 8px; border-radius: 999px; display: inline-block; flex-shrink: 0; }}
.dot-green {{ background: #17B26A; }}
.dot-red   {{ background: var(--c-alert); }}

/* ── sidebar ── */
section[data-testid="stSidebar"] {{
  background: linear-gradient(180deg,rgba(238,243,248,1) 0%,rgba(245,247,250,1) 100%);
  border-right: 1px solid rgba(47,93,140,.12);
  min-width: var(--sidebar-w) !important;
  max-width: var(--sidebar-w) !important;
  overflow: hidden !important; /* no vertical scrolling */
}}

/* tighten sidebar content so it sits higher */
div[data-testid="stSidebarContent"] {{
  padding-top: 0px !important;
  padding-bottom: 8px !important;
  overflow: hidden !important;
}}
div[data-testid="stSidebarContent"] > div {{
  padding-top: 0 !important;
}}

/* hide collapse control: fixed (not collapsible) */
button[data-testid="stSidebarCollapsedControl"] {{
  display: none !important;
}}
button[kind="headerNoPadding"][data-testid="stBaseButton-headerNoPadding"] {{
  display: none !important;
}}

/* ── sidebar header ── */
.sidebar-header {{
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0px 0px 0px;
}}
.sidebar-sub {{
  display: none;
}}
.sidebar-logo {{
  width: 38px; height: 38px; flex-shrink: 0;
  border-radius: 12px;
  background: rgba(47,93,140,.12);
  display: flex; align-items: center; justify-content: center;
  border: 1px solid rgba(47,93,140,.18);
  font-weight: 900; color: {PRIMARY}; font-size: 13px;
}}
.sidebar-title   {{ font-weight: 900; font-size: var(--fs-body); line-height: 1.15; color: var(--c-text); }}
.sidebar-sub     {{ font-size: var(--fs-sm); color: var(--c-muted); margin-top: 2px; }}
.nav-label       {{ font-size: var(--fs-sm); color: var(--c-muted); margin: 10px 0 8px 2px; font-weight: 700; }}

/* ── nav buttons ── */
div.stButton > button {{
  border-radius: 12px;
  font-weight: 500;
  font-size: var(--fs-body);
  padding: 1px 3px;
  border: 1px solid rgba(47,93,140,.12);
  transition: all .15s ease;
  line-height: 1.3;
}}
/* reduce vertical gaps between buttons */
div.stButton {{
  margin-bottom: 0px !important;
}}
div.stButton > button:hover {{
  border-color: rgba(47,93,140,.3);
  box-shadow: 0 10px 24px rgba(15,26,36,.08);
  transform: translateY(-1px);
}}

/* nav item — full width, icon + text left-aligned, vertically centred */
.nav-button div.stButton > button {{
  justify-content: flex-start;
  width: 100%;
  min-height: 40px;
  background: rgba(255,255,255,.88);
  display: flex;
  align-items: center;
}}

/* sidebar is fixed expanded (no collapsed state) */
.nav-button-active div.stButton > button {{
  background: linear-gradient(135deg,rgba(47,93,140,.14),rgba(107,140,163,.14));
  color: var(--c-text);
  border-color: rgba(47,93,140,.28);
  box-shadow: 0 12px 28px rgba(47,93,140,.12);
}}

/* primary CTA */
.big-primary div.stButton > button {{
  padding: 14px 16px;
  font-size: var(--fs-h2);
}}

/* ── sidebar user panel（緊接導覽列，避免被推到最底部） ── */
.sidebar-footer-anchor {{
  display: block;
  margin-top: 6px;
  padding-top: 8px;
  border-top: 1px solid rgba(47,93,140,.1);
}}
section[data-testid="stSidebar"] div:has(.sidebar-footer-anchor) {{
  margin-top: 0 !important;
  flex-grow: 0 !important;
}}
section[data-testid="stSidebar"] div:has(.sidebar-footer-anchor) ~ div {{
  flex-grow: 0 !important;
  margin-top: 0 !important;
}}
section[data-testid="stSidebar"] div[data-testid="stVerticalBlock"]:has(.sidebar-user) {{
  flex-grow: 0 !important;
  margin-top: 0 !important;
  padding-top: 0 !important;
}}
.sidebar-user {{
  padding: 2px 4px 4px 0;
  font-size: var(--fs-sm);
  line-height: 1.25;
}}
.sidebar-user .name {{ font-weight: 900; font-size: var(--fs-body); margin-top: 1px; color: var(--c-text); }}
.sidebar-user .role {{ color: var(--c-muted); margin-top: 1px; font-size: var(--fs-sm); }}

/* small icon button next to user info */
.sidebar-logout div.stButton > button {{
  min-height: 40px !important;
  min-width: 48px !important;
  padding: 8px 14px !important;
  border-radius: 12px !important;
  border: 1px solid rgba(47,93,140,.12) !important;
  background: rgba(255,255,255,.92) !important;
  box-shadow: 0 8px 18px rgba(15,26,36,.08) !important;
}}
.sidebar-logout div.stButton > button:hover {{
  border-color: rgba(47,93,140,.28) !important;
}}

/* ══════════ 登入頁（:has(.login-page-anchor)）淺色動態背景 ══════════ */
@keyframes login-light-breathe {{
  0%, 100% {{ background-position: 0% 40%, 100% 70%, 20% 90%, 85% 25%, center; }}
  50% {{ background-position: 100% 55%, 0% 35%, 75% 15%, 15% 75%, center; }}
}}
@keyframes login-grid-drift-light {{
  0% {{ transform: translate(0, 0) rotate(0deg); opacity: .35; }}
  50% {{ transform: translate(-14px, 10px) rotate(0.4deg); opacity: .52; }}
  100% {{ transform: translate(0, 0) rotate(0deg); opacity: .35; }}
}}
@keyframes login-dot-bob {{
  0%, 100% {{ transform: translateY(0); opacity: .48; }}
  50% {{ transform: translateY(-12px); opacity: .82; }}
}}
@keyframes login-shape-a {{
  0%, 100% {{ transform: translate(0, 0) scale(1) rotate(0deg); }}
  33% {{ transform: translate(26px, -32px) scale(1.05) rotate(10deg); }}
  66% {{ transform: translate(-16px, 20px) scale(0.96) rotate(-7deg); }}
}}
@keyframes login-shape-b {{
  0%, 100% {{ transform: translate(0, 0) scale(1) rotate(0deg); }}
  40% {{ transform: translate(-28px, 24px) scale(1.06) rotate(-12deg); }}
  70% {{ transform: translate(22px, -14px) scale(0.94) rotate(9deg); }}
}}
@keyframes login-shape-c {{
  0%, 100% {{ transform: translate(0, 0); border-radius: 52% 48% 45% 55% / 48% 52% 55% 45%; }}
  50% {{ transform: translate(16px, 18px); border-radius: 42% 58% 55% 45% / 55% 45% 48% 52%; }}
}}

.stApp:has(.login-page-anchor) {{
  background-color: #eef2f7 !important;
  background-image:
    radial-gradient(ellipse 90% 70% at 8% 12%, rgba(147, 197, 253, 0.52), transparent 58%),
    radial-gradient(ellipse 75% 65% at 92% 8%, rgba(216, 180, 254, 0.42), transparent 55%),
    radial-gradient(ellipse 70% 60% at 88% 92%, rgba(125, 211, 252, 0.48), transparent 52%),
    radial-gradient(ellipse 65% 55% at 5% 88%, rgba(254, 215, 170, 0.4), transparent 50%),
    linear-gradient(178deg, #fbfcfe 0%, #f1f5f9 42%, #eef2f7 100%);
  background-size: 130% 130%, 130% 130%, 130% 130%, 130% 130%, 100% 100%;
  background-position: 0% 40%, 100% 70%, 20% 90%, 85% 25%, center;
  animation: login-light-breathe 26s ease-in-out infinite;
}}
.stApp:has(.login-page-anchor)::before {{
  content: "";
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background-image:
    linear-gradient(rgba(47, 93, 140, 0.042) 1px, transparent 1px),
    linear-gradient(90deg, rgba(47, 93, 140, 0.042) 1px, transparent 1px);
  background-size: 52px 52px;
  mask-image: radial-gradient(ellipse 95% 85% at 50% 40%, black 0%, transparent 72%);
  animation: login-grid-drift-light 20s ease-in-out infinite;
}}
.stApp:has(.login-page-anchor)::after {{
  content: "";
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background-image:
    radial-gradient(circle 5px at 12% 28%, rgba(59, 130, 246, 0.2), transparent 6px),
    radial-gradient(circle 4px at 78% 18%, rgba(168, 85, 247, 0.16), transparent 5px),
    radial-gradient(circle 4px at 66% 72%, rgba(14, 165, 233, 0.18), transparent 5px),
    radial-gradient(circle 5px at 22% 82%, rgba(244, 114, 182, 0.14), transparent 6px),
    radial-gradient(circle 3px at 90% 55%, rgba(34, 197, 94, 0.16), transparent 4px);
  animation: login-dot-bob 7s ease-in-out infinite;
}}

.login-deco {{
  position: fixed;
  inset: 0;
  z-index: 1;
  pointer-events: none;
  overflow: hidden;
}}
.login-deco .login-shape {{
  position: absolute;
  opacity: 0.4;
}}
.login-deco .login-shape.s1 {{
  width: min(28vw, 200px);
  height: min(28vw, 200px);
  left: -4%;
  top: 12%;
  border-radius: 62% 38% 48% 52% / 55% 45% 52% 48%;
  background: linear-gradient(145deg, rgba(147, 197, 253, 0.92), rgba(99, 102, 241, 0.32));
  animation: login-shape-a 19s ease-in-out infinite;
}}
.login-deco .login-shape.s2 {{
  width: min(22vw, 160px);
  height: min(22vw, 160px);
  right: -2%;
  top: 8%;
  border-radius: 48% 52% 58% 42% / 52% 48% 45% 55%;
  background: linear-gradient(200deg, rgba(233, 213, 255, 0.88), rgba(125, 211, 252, 0.38));
  animation: login-shape-b 23s ease-in-out infinite;
  animation-delay: -4s;
}}
.login-deco .login-shape.s3 {{
  width: min(36vw, 260px);
  height: min(36vw, 260px);
  right: 8%;
  bottom: -6%;
  border-radius: 45% 55% 52% 48% / 48% 52% 45% 55%;
  background: linear-gradient(160deg, rgba(186, 230, 253, 0.62), rgba(165, 180, 252, 0.32));
  animation: login-shape-c 21s ease-in-out infinite;
  animation-delay: -2s;
}}
.login-deco .login-shape.s4 {{
  width: min(18vw, 120px);
  height: min(18vw, 120px);
  left: 18%;
  bottom: 14%;
  border-radius: 50%;
  background: linear-gradient(135deg, rgba(254, 202, 202, 0.72), rgba(253, 224, 200, 0.48));
  animation: login-shape-a 16s ease-in-out infinite reverse;
  animation-delay: -8s;
}}
.login-deco .login-shape.s5 {{
  width: 72px;
  height: 72px;
  left: 42%;
  top: 6%;
  border-radius: 16px;
  background: linear-gradient(135deg, rgba(52, 211, 153, 0.32), rgba(56, 189, 248, 0.28));
  animation: login-shape-b 14s ease-in-out infinite;
  animation-delay: -6s;
}}

.stApp:has(.login-page-anchor) .main .block-container {{
  max-width: 900px;
  margin-left: auto;
  margin-right: auto;
  padding-top: 2rem;
  position: relative;
  z-index: 2;
  background: transparent !important;
}}
.stApp:has(.login-page-anchor) [data-testid="stAppViewContainer"] {{
  position: relative;
  z-index: 2;
  background: transparent !important;
}}
.stApp:has(.login-page-anchor) section[data-testid="stSidebar"] {{
  display: none !important;
}}
.stApp:has(.login-page-anchor) [data-testid="stAppViewContainer"] > .main {{
  margin-left: 0 !important;
  width: 100% !important;
  background: transparent !important;
}}

.stApp:has(.login-page-anchor) .main {{
  color: #0f172a;
}}
.stApp:has(.login-page-anchor) .main label {{
  color: #475569 !important;
}}

.stApp:has(.login-page-anchor) div[data-testid="stVerticalBlockBorderWrapper"] {{
  background: rgba(255, 255, 255, 0.84) !important;
  border: 1px solid rgba(47, 93, 140, 0.12) !important;
  box-shadow:
    0 0 0 1px rgba(255, 255, 255, 0.9) inset,
    0 18px 40px rgba(15, 26, 36, 0.08),
    0 4px 24px rgba(59, 130, 246, 0.06) !important;
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
}}

.login-hero {{
  text-align: center;
  margin-bottom: 1.6rem;
  position: relative;
  z-index: 2;
}}
.login-brand-mark {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  margin: 0 auto 12px;
  border-radius: 14px;
  font-weight: 900;
  font-size: 15px;
  letter-spacing: -0.02em;
  color: #1d4ed8;
  border: 1px solid rgba(59, 130, 246, 0.28);
  background: linear-gradient(145deg, rgba(255, 255, 255, 0.95), rgba(191, 219, 254, 0.52));
  box-shadow: 0 8px 28px rgba(59, 130, 246, 0.14);
}}
.login-sys-title {{
  font-size: clamp(1.5rem, 4vw, 1.85rem);
  font-weight: 900;
  letter-spacing: 0.06em;
  background: linear-gradient(110deg, #1e3a8a 0%, #2563eb 38%, #0891b2 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  margin-bottom: 8px;
  line-height: 1.25;
}}
.login-sys-tagline {{
  font-size: 0.8125rem;
  color: #64748b;
  letter-spacing: 0.08em;
}}
.login-card-title {{
  font-size: 1.05rem;
  font-weight: 800;
  color: #0f172a;
  margin-bottom: 2px;
}}
.login-card-desc {{
  font-size: 0.8125rem;
  color: #64748b;
  margin-bottom: 14px;
}}

/* 密碼列：Base Web 外框包住輸入與顯示／隱藏按鈕；按鈕在上層可點 */
.stApp:has(.login-page-anchor) div[data-testid="stTextInput"]:has([data-baseweb="base-input"]) [data-baseweb="base-input"] {{
  border-radius: 12px !important;
  overflow: hidden;
  align-items: stretch !important;
}}
.stApp:has(.login-page-anchor) div[data-testid="stTextInput"]:has([data-baseweb="base-input"]) [data-baseweb="base-input"] input {{
  border: none !important;
  box-shadow: none !important;
  border-radius: 0 !important;
}}
.stApp:has(.login-page-anchor) div[data-testid="stTextInput"]:has([data-baseweb="base-input"]) [data-baseweb="base-input"] button[type="button"] {{
  position: relative;
  z-index: 4;
  align-self: stretch;
  min-height: 100%;
}}

/* 不顯示 Press Enter…（表單已 enter_to_submit=False，此為保險） */
.stApp:has(.login-page-anchor) [data-testid="InputInstructions"] {{
  display: none !important;
}}

/* ── responsive breakpoints ── */
@media (max-width: 1200px) {{
  :root {{ --sidebar-w: 290px; }}
}}
@media (max-width: 992px) {{
  .block-container {{ padding-left: 1rem; padding-right: 1rem; }}
}}
@media (max-width: 768px) {{
  :root {{ --sidebar-w: 260px; }}
}}
</style>
""", unsafe_allow_html=True)

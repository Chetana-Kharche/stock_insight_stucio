"""Global design system (CSS) for the Streamlit app.

Palette: navy #0B1F3A / blue #1D4ED8 for headings, green #059669 for accents,
soft grey page background and white cards with subtle shadows.
"""

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');

:root {
  --sis-navy: #0B1F3A;
  --sis-navy-2: #0B3C5D;
  --sis-blue: #1D4ED8;
  --sis-blue-soft: #EFF4FF;
  --sis-green: #059669;
  --sis-green-soft: #ECFDF5;
  --sis-orange: #E8710A;
  --sis-red: #DC2626;
  --sis-amber: #B45309;
  --sis-ink: #0F172A;
  --sis-text: #334155;
  --sis-muted: #64748B;
  --sis-line: #E6EAF0;
  --sis-bg: #F5F7FB;
  --sis-card: #FFFFFF;
  --sis-radius: 14px;
  --sis-shadow: 0 1px 2px rgba(15,23,42,.04), 0 4px 16px rgba(15,23,42,.05);
}

/* ------------------------------------------------------------ base */
html, body, [class*="css"], .stApp, .stMarkdown, button, input, textarea, select {
  font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif;
}
.stApp { background: var(--sis-bg); }
.block-container { padding-top: 1.8rem; padding-bottom: 7rem; max-width: 1320px; }
div[data-testid="stVerticalBlock"] { gap: 0.9rem; }
h1 { color: var(--sis-navy) !important; font-weight: 800 !important; letter-spacing: -0.02em; }
h2, h3 { color: var(--sis-blue) !important; font-weight: 700 !important; letter-spacing: -0.01em; }
h4 { color: var(--sis-navy-2) !important; font-weight: 700 !important; }
p, li { color: var(--sis-text); line-height: 1.65; }
a { color: var(--sis-blue); text-decoration: none; }
a:hover { text-decoration: underline; }
hr { margin: 1.2rem 0 !important; border-color: var(--sis-line) !important; }

/* ------------------------------------------------------------ sidebar */
section[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #0B1F3A 0%, #0B3C5D 100%);
  border-right: none;
}
section[data-testid="stSidebar"] * { color: #E2E8F0; }
section[data-testid="stSidebar"] h3 { color: #FFFFFF !important; font-size: 1.15rem; }
section[data-testid="stSidebar"] code { background: rgba(255,255,255,.12); color: #A7F3D0; }
section[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.15) !important; }
section[data-testid="stSidebar"] [role="radiogroup"] { gap: 4px; }
section[data-testid="stSidebar"] [role="radiogroup"] label {
  padding: 10px 14px; border-radius: 10px; width: 100%; transition: background .15s ease;
}
section[data-testid="stSidebar"] [role="radiogroup"] label:hover { background: rgba(255,255,255,.08); }
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
  background: rgba(59,130,246,.28); box-shadow: inset 3px 0 0 #34D399;
}
section[data-testid="stSidebar"] [role="radiogroup"] label p { font-weight: 600; font-size: .95rem; color: #FFFFFF; }
section[data-testid="stSidebar"] .stButton > button {
  background: rgba(255,255,255,.08) !important; border: 1px solid rgba(255,255,255,.2) !important;
  color: #FFFFFF !important;
}

/* ------------------------------------------------------------ widgets */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
  border-radius: 10px !important; font-weight: 600 !important; padding: .55rem 1.1rem !important;
  border: 1px solid var(--sis-line) !important; transition: all .15s ease; min-height: 2.6rem;
}
.stButton > button:hover, .stDownloadButton > button:hover { border-color: var(--sis-blue) !important;
  color: var(--sis-blue) !important; transform: translateY(-1px); }
button[kind="primary"], button[data-testid="stBaseButton-primary"],
button[kind="primaryFormSubmit"], button[data-testid="stBaseButton-primaryFormSubmit"] {
  background: linear-gradient(135deg, #1D4ED8 0%, #0B3C5D 100%) !important; color: #FFFFFF !important;
  border: none !important; box-shadow: 0 6px 16px rgba(29,78,216,.25);
}
button[kind="primary"]:hover, button[data-testid="stBaseButton-primary"]:hover { color: #FFFFFF !important; }
button[kind="primary"] p, button[data-testid="stBaseButton-primary"] p,
button[kind="primaryFormSubmit"] p, button[data-testid="stBaseButton-primaryFormSubmit"] p { color: #FFFFFF !important; }

div[data-baseweb="input"], div[data-baseweb="select"] > div, div[data-baseweb="textarea"] {
  border-radius: 10px !important; background: #FFFFFF !important;
}
div[data-testid="stTextInput"] label p, div[data-testid="stSelectbox"] label p,
div[data-testid="stMultiSelect"] label p { font-weight: 600; color: var(--sis-navy-2); font-size: .88rem; }

/* tabs */
.stTabs [data-baseweb="tab-list"] { gap: 6px; border-bottom: 2px solid var(--sis-line); }
.stTabs [data-baseweb="tab"] {
  padding: 10px 20px; border-radius: 10px 10px 0 0; font-weight: 600; color: var(--sis-muted);
  background: transparent;
}
.stTabs [data-baseweb="tab"] p { font-weight: 600; font-size: .95rem; }
.stTabs [aria-selected="true"] { color: var(--sis-blue) !important; background: var(--sis-blue-soft); }
.stTabs [data-baseweb="tab-highlight"] { background-color: var(--sis-blue) !important; height: 3px; }
.stTabs [data-baseweb="tab-panel"] { padding-top: 1.2rem; }

/* bordered containers, expanders, metrics */
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stVerticalBlock"]) {
  border-radius: var(--sis-radius);
}
div[data-testid="stExpander"] details { border-radius: 12px; border: 1px solid var(--sis-line); background: #fff; }
div[data-testid="stExpander"] summary p { font-weight: 600; color: var(--sis-navy-2); }
div[data-testid="stMetric"] {
  background: #FFFFFF; border: 1px solid var(--sis-line); border-radius: var(--sis-radius);
  padding: 16px 18px; box-shadow: var(--sis-shadow);
}
div[data-testid="stMetricLabel"] p { color: var(--sis-muted); font-weight: 600; text-transform: uppercase;
  font-size: .72rem; letter-spacing: .06em; }
div[data-testid="stMetricValue"] { color: var(--sis-navy); font-weight: 800; }
div[data-testid="stAlert"] { border-radius: 12px; }
div[data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; border: 1px solid var(--sis-line); }
div[data-testid="stPlotlyChart"] { background: #fff; border: 1px solid var(--sis-line); border-radius: var(--sis-radius);
  padding: 6px; box-shadow: var(--sis-shadow); }

/* ------------------------------------------------------------ page header / hero */
.sis-hero {
  background: linear-gradient(120deg, #0B1F3A 0%, #0B3C5D 55%, #1D4ED8 100%);
  border-radius: 18px; padding: 26px 30px; color: #fff; margin-bottom: 8px;
  box-shadow: 0 10px 30px rgba(11,31,58,.18); position: relative; overflow: hidden;
}
.sis-hero::after { content: ""; position: absolute; right: -60px; top: -60px; width: 220px; height: 220px;
  border-radius: 50%; background: radial-gradient(circle, rgba(52,211,153,.35), transparent 70%); }
.sis-hero .eyebrow { font-size: .72rem; letter-spacing: .14em; text-transform: uppercase; color: #6EE7B7;
  font-weight: 700; margin-bottom: 6px; }
.sis-hero .title { font-size: 1.85rem; font-weight: 800; letter-spacing: -0.02em; color: #FFFFFF; line-height: 1.2; }
.sis-hero .subtitle { font-size: .98rem; color: #CBD5E1; margin-top: 6px; max-width: 780px; }
.sis-hero .chips { margin-top: 14px; display: flex; gap: 8px; flex-wrap: wrap; position: relative; z-index: 1; }
.sis-chip { font-size: .72rem; font-weight: 600; padding: 4px 11px; border-radius: 999px;
  background: rgba(255,255,255,.12); border: 1px solid rgba(255,255,255,.22); color: #E2E8F0; }

/* ------------------------------------------------------------ section titles */
.sis-section { display: flex; align-items: flex-start; gap: 12px; margin: 22px 0 6px 0; }
.sis-section .bar { width: 5px; min-height: 30px; border-radius: 4px; background: var(--sis-blue); margin-top: 2px; }
.sis-section.green .bar { background: var(--sis-green); }
.sis-section .t { font-size: 1.22rem; font-weight: 800; color: var(--sis-blue); letter-spacing: -0.01em; line-height: 1.25; }
.sis-section.green .t { color: var(--sis-green); }
.sis-section .s { font-size: .86rem; color: var(--sis-muted); margin-top: 2px; }
.sis-step { display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px;
  border-radius: 50%; background: var(--sis-green); color: #fff; font-weight: 800; font-size: .8rem; margin-right: 8px; }

/* ------------------------------------------------------------ cards */
.sis-card { border: 1px solid var(--sis-line); border-radius: var(--sis-radius); padding: 20px 22px;
  background: var(--sis-card); margin-bottom: 14px; box-shadow: var(--sis-shadow); }
.sis-card h3 { margin: 0 0 2px 0; font-size: 1.08rem; color: var(--sis-blue) !important; }
.sis-card h4 { margin: 14px 0 8px 0; font-size: .95rem; color: var(--sis-green) !important; }
.sis-sub { color: var(--sis-muted); font-size: .82rem; margin-bottom: 12px; }
.sis-tag { display: inline-block; font-size: .66rem; font-weight: 700; letter-spacing: .06em; color: #047857;
  background: var(--sis-green-soft); border: 1px solid #A7F3D0; border-radius: 999px; padding: 3px 10px;
  margin-left: 10px; vertical-align: middle; }
.sis-head { display: flex; justify-content: space-between; gap: 24px; flex-wrap: wrap; align-items: flex-start; }
.sis-head .name { font-size: 1.7rem; font-weight: 800; color: var(--sis-navy); letter-spacing: -0.02em; }
.sis-mono { font-family: 'JetBrains Mono', ui-monospace, Menlo, Consolas, monospace; font-size: .82rem; color: #475569; }
.sis-kv { display: grid; grid-template-columns: auto auto; column-gap: 28px; row-gap: 6px; font-size: .86rem;
  background: #F8FAFC; border: 1px solid var(--sis-line); border-radius: 12px; padding: 12px 16px; }
.sis-kv .k { color: var(--sis-muted); } .sis-kv .v { text-align: right; font-family: 'JetBrains Mono', monospace;
  color: var(--sis-ink); }

/* ratio tiles */
.sis-grid { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 14px; }
@media (max-width: 900px) { .sis-grid { grid-template-columns: repeat(2, minmax(0,1fr)); } }
.sis-ratio { border: 1px solid var(--sis-line); border-radius: 12px; padding: 14px 16px; background: #fff;
  border-top: 3px solid var(--sis-blue); }
.sis-ratio:nth-child(3n+2) { border-top-color: var(--sis-green); }
.sis-ratio:nth-child(3n) { border-top-color: #0EA5E9; }
.sis-ratio .n { font-size: .7rem; letter-spacing: .07em; color: var(--sis-muted); font-weight: 700; text-transform: uppercase; }
.sis-ratio .v { font-size: 1.2rem; font-weight: 800; font-family: 'JetBrains Mono', monospace; margin: 6px 0 2px 0;
  color: var(--sis-navy); }
.sis-ratio .u { font-size: .68rem; color: #94A3B8; }

/* data tables */
.sis-tablewrap { overflow-x: auto; border: 1px solid var(--sis-line); border-radius: 12px; background: #fff; }
table.sis-table { border-collapse: collapse; width: 100%; font-size: .83rem; }
table.sis-table th { background: #F1F5FB; color: var(--sis-navy-2); font-weight: 700; text-align: right;
  padding: 10px 14px; white-space: nowrap; border-bottom: 1px solid var(--sis-line); font-size: .78rem;
  letter-spacing: .02em; }
table.sis-table th:first-child, table.sis-table td:first-child { text-align: left; position: sticky; left: 0;
  background: #fff; z-index: 1; border-right: 1px solid var(--sis-line); min-width: 180px; }
table.sis-table th:first-child { background: #F1F5FB; }
table.sis-table td { padding: 9px 14px; text-align: right; white-space: nowrap; border-bottom: 1px solid #F1F5F9;
  font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace; color: var(--sis-ink); }
table.sis-table td:first-child { font-family: 'Inter', sans-serif; font-weight: 500; }
table.sis-table tbody tr:hover td { background: #F8FAFF; }
table.sis-table tr.bold td { font-weight: 700; }
table.sis-table tr.sub td { color: var(--sis-muted); font-size: .76rem; background: #FCFCFD; }
table.sis-table tr.sub td:first-child { padding-left: 30px; background: #FCFCFD; }
table.sis-table .plus { color: var(--sis-green); font-weight: 800; }

/* unit label shown above every chart and table */
.sis-unit { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 2px 0 8px 0; font-size: .78rem;
  color: var(--sis-muted); }
.sis-unit b { background: var(--sis-green-soft); color: var(--sis-green); border: 1px solid #BBF7D0;
  padding: 2px 10px; border-radius: 999px; font-weight: 700; white-space: nowrap; }
.sis-src { font-size: .72rem; font-weight: 700; padding: 2px 9px; border-radius: 999px; background: var(--sis-blue-soft);
  color: var(--sis-blue); white-space: nowrap; }
table.sis-table.wrap td { white-space: normal; text-align: left; font-family: 'Inter', sans-serif; }
table.sis-table.wrap th { text-align: left; }
table.sis-table.wrap td.val { font-weight: 700; white-space: nowrap; }

/* notes, badges, report */
.sis-note { border-left: 3px solid #F59E0B; background: #FFFBEB; color: #92400E; padding: 10px 14px;
  font-size: .8rem; border-radius: 8px; margin-top: 10px; }
.sis-badge { display: inline-block; padding: 5px 14px; border-radius: 999px; font-weight: 800; font-size: .78rem;
  color: #fff; letter-spacing: .06em; }
.sis-Positive { background: var(--sis-green); } .sis-Neutral { background: var(--sis-amber); }
.sis-Cautious { background: var(--sis-red); }
.sis-banner { background: linear-gradient(120deg, #0B1F3A, #1D4ED8); color: #fff; padding: 14px 18px;
  border-radius: 12px; font-weight: 700; font-size: 1.05rem; margin: 12px 0 14px 0; line-height: 1.45; }
.sis-summary { background: #F8FAFC; border-left: 4px solid var(--sis-green); padding: 14px 18px;
  border-radius: 10px; line-height: 1.7; color: var(--sis-text); }
.sis-h2 { color: var(--sis-blue); font-weight: 800; font-size: 1.06rem; margin: 20px 0 6px 0;
  padding-bottom: 6px; border-bottom: 2px solid var(--sis-blue-soft); }
.sis-h2.green { color: var(--sis-green); border-bottom-color: var(--sis-green-soft); }
.sis-doc ul { padding-left: 18px; margin: 0; }
.sis-doc li { margin-bottom: 8px; font-size: .87rem; }
.sis-doc .d { color: var(--sis-muted); font-size: .76rem; }
.sis-list { list-style: none; padding: 0; margin: 0; }
.sis-list li { padding: 8px 0 8px 26px; position: relative; border-bottom: 1px dashed var(--sis-line); font-size: .9rem; }
.sis-list li::before { content: "✓"; position: absolute; left: 4px; top: 8px; color: var(--sis-green); font-weight: 800; }
.sis-list.risk li::before { content: "!"; color: var(--sis-red); left: 8px; }
.sis-list.watch li::before { content: "›"; color: var(--sis-blue); left: 8px; font-size: 1.1rem; top: 5px; }

/* empty state + steps */
.sis-empty { text-align: center; padding: 38px 20px; border: 1.5px dashed #CBD5E1; border-radius: 16px; background: #fff; }
.sis-empty .big { font-size: 1.15rem; font-weight: 800; color: var(--sis-navy); }
.sis-empty .small { color: var(--sis-muted); margin-top: 6px; font-size: .9rem; }
.sis-steps { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 14px; margin-top: 18px; text-align: left; }
.sis-steps div { background: #F8FAFC; border: 1px solid var(--sis-line); border-radius: 12px; padding: 14px; font-size: .86rem; }
.sis-steps b { color: var(--sis-blue); display: block; margin-bottom: 4px; }

/* news */
.sis-news { padding: 14px 16px; border: 1px solid var(--sis-line); border-radius: 12px; background: #fff;
  margin-bottom: 10px; box-shadow: var(--sis-shadow); }
.sis-news a { font-weight: 700; color: var(--sis-navy); font-size: .95rem; }
.sis-news .meta { color: var(--sis-muted); font-size: .78rem; margin-top: 4px; }
.sis-news .src { color: var(--sis-green); font-weight: 700; }

/* auth page */
.sis-auth-brand { background: linear-gradient(150deg, #0B1F3A 0%, #0B3C5D 55%, #1D4ED8 100%); color: #fff;
  border-radius: 20px; padding: 38px 34px; min-height: 520px; box-shadow: 0 16px 40px rgba(11,31,58,.22); }
.sis-auth-brand .logo { font-size: 1.9rem; font-weight: 800; letter-spacing: -0.02em; color: #fff; }
.sis-auth-brand .logo span { color: #34D399; }
.sis-auth-brand .tag { color: #CBD5E1; margin: 8px 0 26px 0; font-size: 1rem; line-height: 1.6; }
.sis-auth-brand .feat { display: flex; gap: 12px; margin-bottom: 16px; align-items: flex-start; }
.sis-auth-brand .ic { width: 30px; height: 30px; border-radius: 9px; background: rgba(52,211,153,.18);
  color: #34D399; display: flex; align-items: center; justify-content: center; font-weight: 800; flex: none; }
.sis-auth-brand .ft { font-weight: 700; color: #fff; font-size: .95rem; }
.sis-auth-brand .fd { color: #94A3B8; font-size: .84rem; }
.sis-auth-title { font-size: 1.6rem; font-weight: 800; color: var(--sis-navy); margin-top: 10px; }
.sis-auth-sub { color: var(--sis-muted); margin-bottom: 8px; }

/* ------------------------------------------------------------ floating chatbot button */
.st-key-chat_fab { position: fixed !important; right: 28px; bottom: 26px; z-index: 999990; width: auto !important; }
.st-key-chat_fab button {
  background: linear-gradient(135deg, #059669 0%, #1D4ED8 100%) !important; color: #fff !important;
  border-radius: 999px !important; padding: 12px 22px !important; border: none !important;
  box-shadow: 0 10px 28px rgba(29,78,216,.35) !important;
}
.st-key-chat_fab button p { color: #fff !important; font-weight: 700 !important; }
div[data-testid="stPopoverBody"] { width: 460px !important; max-width: 92vw; border-radius: 16px !important; }
.sis-chat-head { background: linear-gradient(120deg, #0B1F3A, #1D4ED8); color: #fff; border-radius: 12px;
  padding: 12px 14px; margin-bottom: 4px; }
.sis-chat-head .a { font-weight: 800; font-size: 1rem; color: #fff; }
.sis-chat-head .b { font-size: .76rem; color: #CBD5E1; }
</style>
"""

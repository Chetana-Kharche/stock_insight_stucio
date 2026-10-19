"""Design system (CSS) - colours follow Value Research Online.

Value Research palette (read from valueresearchonline.com):
  primary blue  #1C4DA0   link blue #1C509D   deep navy #163A5F
  warm page bg  #FEF1E8   accent orange #FFA41C   green #12783C
  text #212529  muted #595959  warm border #E8E4DD   white header and cards
"""

CSS = """
<style>
:root {
  --vr-blue: #1C4DA0;
  --vr-blue-2: #1C509D;
  --vr-blue-soft: #EAF0FA;
  --vr-navy: #163A5F;
  --vr-peach: #FEF1E8;
  --vr-cream: #FFF8F3;
  --vr-orange: #FFA41C;
  --vr-orange-soft: #FFF3DD;
  --vr-green: #12783C;
  --vr-green-soft: #E7F5EC;
  --vr-red: #C62828;
  --vr-red-soft: #FDECEC;
  --vr-amber: #A86200;
  --vr-ink: #212529;
  --vr-text: #3C4043;
  --vr-muted: #595959;
  --vr-line: #E8E4DD;
  --vr-line-2: #F0ECE6;
  --vr-card: #FFFFFF;
  --vr-radius: 10px;
  --vr-shadow: 0 1px 2px rgba(22,58,95,.05), 0 6px 18px rgba(22,58,95,.06);
  --vr-font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif;
  --vr-mono: ui-monospace, "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;

  /* aliases used by older components */
  --sis-navy: var(--vr-navy); --sis-navy-2: var(--vr-navy); --sis-blue: var(--vr-blue);
  --sis-blue-soft: var(--vr-blue-soft); --sis-green: var(--vr-green); --sis-green-soft: var(--vr-green-soft);
  --sis-red: var(--vr-red); --sis-amber: var(--vr-amber); --sis-ink: var(--vr-ink); --sis-text: var(--vr-text);
  --sis-muted: var(--vr-muted); --sis-line: var(--vr-line); --sis-radius: var(--vr-radius); --sis-shadow: var(--vr-shadow);
}

/* ------------------------------------------------------------ base */
html, body, [class*="css"], .stApp, .stMarkdown, button, input, textarea, select { font-family: var(--vr-font); }
.stApp { background: var(--vr-peach); }
header[data-testid="stHeader"] { background: transparent; height: 0; }
div[data-testid="stToolbar"] { right: 8px; }
section[data-testid="stSidebar"], div[data-testid="stSidebarCollapsedControl"] { display: none !important; }
.block-container { padding-top: 0.6rem !important; padding-bottom: 7rem; max-width: 1280px; }
div[data-testid="stVerticalBlock"] { gap: 0.85rem; }
h1, h2, h3, h4 { color: var(--vr-navy) !important; font-weight: 700 !important; letter-spacing: -0.01em; }
p, li { color: var(--vr-text); line-height: 1.6; }
a { color: var(--vr-blue-2); text-decoration: none; }
a:hover { text-decoration: underline; }
hr { margin: 1rem 0 !important; border-color: var(--vr-line) !important; }

/* ------------------------------------------------------------ top bar (white card) */
.st-key-topbar { background: #FFFFFF; border: 1px solid var(--vr-line); border-radius: 12px;
  padding: 6px 16px; margin: 6px 0 4px; box-shadow: 0 2px 10px rgba(22,58,95,.06); }
.vr-brand { display: flex; align-items: center; gap: 10px; white-space: nowrap; }
.vr-brand .mark { width: 34px; height: 34px; border-radius: 8px; background: var(--vr-blue); color: #fff; flex: none;
  display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: .95rem; }
.vr-brand .txt { line-height: 1.05; }
.vr-brand .a { font-weight: 800; color: var(--vr-blue); font-size: 1.05rem; }
.vr-brand .b { font-weight: 600; color: var(--vr-navy); font-size: .7rem; letter-spacing: .14em; }

/* ------------------------------------------------------------ tab bars (st.segmented_control) */
.st-key-nav div[data-testid="stButtonGroup"], .st-key-ctab div[data-testid="stButtonGroup"] {
  flex-wrap: wrap; gap: 0; }
.st-key-nav button, .st-key-ctab button {
  background: transparent !important; border: none !important; border-radius: 0 !important; box-shadow: none !important;
  border-bottom: 3px solid transparent !important; padding: 10px 14px 8px !important; min-height: 2.4rem;
  white-space: nowrap !important; }
.st-key-nav button p { font-size: .82rem !important; font-weight: 700 !important; letter-spacing: .07em;
  text-transform: uppercase; color: var(--vr-navy) !important; white-space: nowrap; }
.st-key-ctab button p { font-size: .92rem !important; font-weight: 500 !important; color: #5F6B7A !important;
  white-space: nowrap; }
.st-key-nav button:hover p, .st-key-ctab button:hover p { color: var(--vr-blue) !important; }
.st-key-nav button[data-testid$="Active"], .st-key-ctab button[data-testid$="Active"],
.st-key-nav button[aria-checked="true"], .st-key-ctab button[aria-checked="true"],
.st-key-nav button[aria-pressed="true"], .st-key-ctab button[aria-pressed="true"] {
  border-bottom-color: var(--vr-blue) !important; }
.st-key-nav button[data-testid$="Active"] p, .st-key-ctab button[data-testid$="Active"] p,
.st-key-nav button[aria-checked="true"] p, .st-key-ctab button[aria-checked="true"] p,
.st-key-nav button[aria-pressed="true"] p, .st-key-ctab button[aria-pressed="true"] p {
  color: var(--vr-blue) !important; font-weight: 700 !important; }
.st-key-ctab { background: #FFFFFF; border: 1px solid var(--vr-line); border-radius: 12px; padding: 2px 6px;
  box-shadow: var(--vr-shadow); }
/* company sub-tabs on ONE line like Screener: no wrapping, compact, scroll sideways only if the window is narrow */
.st-key-ctab div[data-testid="stButtonGroup"], .st-key-ctab div[data-testid="stButtonGroup"] > div {
  flex-wrap: nowrap !important; overflow-x: auto; overflow-y: hidden; scrollbar-width: thin; width: 100%;
  justify-content: space-between; }
.st-key-ctab button { flex: 0 0 auto !important; padding: 10px 9px 8px !important; }
.st-key-ctab button p { font-size: .86rem !important; }
.st-key-nav div[data-testid="stButtonGroup"], .st-key-nav div[data-testid="stButtonGroup"] > div {
  flex-wrap: nowrap !important; overflow-x: auto; scrollbar-width: none; }
.st-key-nav button { flex: 0 0 auto !important; padding: 10px 11px 8px !important; }
/* fact-check line under the report headline */
.sis-factcheck { margin: 6px 0 2px; font-size: .84rem; font-weight: 600; color: #12783C; }
/* the big Analysis Report button above the company sub-tabs */
.st-key-go_report button { min-height: 2.9rem; border-radius: 10px !important; box-shadow: 0 4px 12px rgba(28,77,160,.25); }
.st-key-go_report button p { font-size: 1.02rem !important; font-weight: 700 !important; letter-spacing: .02em; }
.vr-report-title { font-size: 1.5rem; font-weight: 800; color: var(--vr-navy); }
/* keep the tabs clear of the brand name */
.st-key-nav { margin-left: 8px; }
.vr-brand { min-width: max-content; padding-right: 8px; }

/* small pill groups (chart period, market movers list) */
.st-key-mv_kind button, .st-key-chart_range button, .st-key-chart_kind button { white-space: nowrap !important; }
.st-key-mv_kind button[data-testid$="Active"], .st-key-chart_range button[data-testid$="Active"],
.st-key-chart_kind button[data-testid$="Active"] { background: var(--vr-blue-soft) !important;
  border-color: var(--vr-blue) !important; }
.st-key-mv_kind button[data-testid$="Active"] p, .st-key-chart_range button[data-testid$="Active"] p,
.st-key-chart_kind button[data-testid$="Active"] p { color: var(--vr-blue) !important; font-weight: 700 !important; }

/* ------------------------------------------------------------ widgets */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button, div[data-testid="stPopover"] > div > button {
  border-radius: 8px !important; font-weight: 600 !important; padding: .5rem 1rem !important;
  border: 1px solid #D9D4CC !important; background: #fff; color: var(--vr-navy) !important;
  transition: all .15s ease; min-height: 2.5rem; }
.stButton > button:hover, .stDownloadButton > button:hover, div[data-testid="stPopover"] > div > button:hover {
  border-color: var(--vr-blue) !important; color: var(--vr-blue) !important; }
button[kind="primary"], button[data-testid="stBaseButton-primary"],
button[kind="primaryFormSubmit"], button[data-testid="stBaseButton-primaryFormSubmit"] {
  background: var(--vr-blue) !important; color: #FFFFFF !important; border: 1px solid var(--vr-blue) !important;
  box-shadow: 0 4px 12px rgba(28,77,160,.22); }
button[kind="primary"]:hover, button[data-testid="stBaseButton-primary"]:hover,
button[data-testid="stBaseButton-primaryFormSubmit"]:hover { background: var(--vr-navy) !important; color: #fff !important; }
button[kind="primary"] p, button[data-testid="stBaseButton-primary"] p,
button[kind="primaryFormSubmit"] p, button[data-testid="stBaseButton-primaryFormSubmit"] p { color: #FFFFFF !important; }
div[data-baseweb="input"], div[data-baseweb="select"] > div, div[data-baseweb="textarea"], div[data-baseweb="base-input"] {
  border-radius: 8px !important; background: #FFFFFF !important; }
div[data-testid="stTextInput"] label p, div[data-testid="stSelectbox"] label p, div[data-testid="stNumberInput"] label p,
div[data-testid="stDateInput"] label p, div[data-testid="stTextArea"] label p, div[data-testid="stMultiSelect"] label p {
  font-weight: 600; color: var(--vr-navy); font-size: .86rem; }
.stTabs [data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid var(--vr-line); }
.stTabs [data-baseweb="tab"] { padding: 10px 16px; font-weight: 600; color: var(--vr-muted); background: transparent; }
.stTabs [aria-selected="true"] { color: var(--vr-blue) !important; }
.stTabs [data-baseweb="tab-highlight"] { background-color: var(--vr-blue) !important; height: 3px; }
.stTabs [data-baseweb="tab-panel"] { padding-top: 1rem; }
div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: var(--vr-radius); }
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stVerticalBlock"]) { background: #FFFFFF; }
div[data-testid="stExpander"] details { border-radius: var(--vr-radius); border: 1px solid var(--vr-line); background: #fff; }
div[data-testid="stExpander"] summary p { font-weight: 600; color: var(--vr-navy); }
div[data-testid="stMetric"] { background: #FFFFFF; border: 1px solid var(--vr-line); border-radius: var(--vr-radius);
  padding: 14px 16px; box-shadow: var(--vr-shadow); }
div[data-testid="stMetricLabel"] p { color: var(--vr-muted); font-weight: 600; text-transform: uppercase;
  font-size: .72rem; letter-spacing: .06em; }
div[data-testid="stMetricValue"] { color: var(--vr-navy); font-weight: 700; }
div[data-testid="stAlert"] { border-radius: var(--vr-radius); }
div[data-testid="stDataFrame"] { border-radius: var(--vr-radius); overflow: hidden; border: 1px solid var(--vr-line); }
div[data-testid="stPlotlyChart"] { background: #fff; border: 1px solid var(--vr-line); border-radius: var(--vr-radius);
  padding: 6px; box-shadow: var(--vr-shadow); }
div[data-testid="stPopoverBody"] { border-radius: 12px !important; }

/* ------------------------------------------------------------ page heading + sections */
.vr-page { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px; flex-wrap: wrap;
  margin: 10px 0 2px; }
.vr-page .t { font-size: 1.75rem; font-weight: 700; color: var(--vr-navy); letter-spacing: -0.02em; line-height: 1.2; }
.vr-page .s { color: var(--vr-muted); font-size: .95rem; margin-top: 4px; max-width: 760px; }
.sis-hero { background: #fff; border: 1px solid var(--vr-line); border-left: 5px solid var(--vr-blue);
  border-radius: var(--vr-radius); padding: 18px 22px; box-shadow: var(--vr-shadow); }
.sis-hero .eyebrow { font-size: .72rem; letter-spacing: .12em; text-transform: uppercase; color: var(--vr-orange);
  font-weight: 700; margin-bottom: 4px; }
.sis-hero .title { font-size: 1.6rem; font-weight: 700; color: var(--vr-navy); line-height: 1.2; }
.sis-hero .subtitle { font-size: .95rem; color: var(--vr-muted); margin-top: 4px; }
.sis-hero .chips { margin-top: 10px; display: flex; gap: 8px; flex-wrap: wrap; }
.sis-chip { font-size: .72rem; font-weight: 600; padding: 3px 10px; border-radius: 999px; background: var(--vr-blue-soft);
  color: var(--vr-blue); border: 1px solid #CBD9F0; }
.sis-section { display: flex; align-items: flex-start; gap: 10px; margin: 18px 0 4px 0; }
.sis-section .bar { width: 4px; min-height: 26px; border-radius: 3px; background: var(--vr-blue); margin-top: 2px; }
.sis-section.green .bar { background: var(--vr-orange); }
.sis-section .t { font-size: 1.15rem; font-weight: 700; color: var(--vr-navy); line-height: 1.25; }
.sis-section .s { font-size: .85rem; color: var(--vr-muted); margin-top: 2px; }
.sis-step { display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px;
  border-radius: 50%; background: var(--vr-blue); color: #fff; font-weight: 700; font-size: .78rem; margin-right: 8px; }
.sis-h2 { color: var(--vr-navy); font-weight: 700; font-size: 1.02rem; margin: 16px 0 6px 0;
  padding-bottom: 6px; border-bottom: 2px solid var(--vr-line); }
.sis-h2.green { color: var(--vr-green); }

/* ------------------------------------------------------------ cards and company header */
.sis-card { border: 1px solid var(--vr-line); border-radius: var(--vr-radius); padding: 18px 20px; background: #fff;
  margin-bottom: 12px; box-shadow: var(--vr-shadow); }
.sis-card h3 { margin: 0 0 2px 0; font-size: 1.05rem; color: var(--vr-navy) !important; }
.sis-card h4 { margin: 14px 0 8px 0; font-size: .92rem; color: var(--vr-blue) !important; }
.sis-sub { color: var(--vr-muted); font-size: .82rem; margin-bottom: 10px; }
.sis-head { display: flex; justify-content: space-between; gap: 20px; flex-wrap: wrap; align-items: flex-start; }
.sis-mono { font-family: var(--vr-mono); font-size: .8rem; color: #5F6B7A; }
.sis-tag { display: inline-block; font-size: .64rem; font-weight: 700; letter-spacing: .06em; color: var(--vr-green);
  background: var(--vr-green-soft); border-radius: 999px; padding: 3px 9px; margin-left: 10px; vertical-align: middle; }

.vr-co { background: #fff; border: 1px solid var(--vr-line); border-radius: 14px; padding: 22px 26px 16px;
  box-shadow: var(--vr-shadow); }
.vr-co .row1 { display: flex; align-items: baseline; gap: 18px; flex-wrap: wrap; }
.vr-co .nm { font-size: 2rem; font-weight: 700; color: var(--vr-ink); letter-spacing: -0.02em; line-height: 1.15; }
.vr-co .px { font-size: 1.35rem; font-weight: 700; color: var(--vr-ink); }
.vr-co .chg { font-weight: 700; font-size: .95rem; margin-left: 6px; }
.vr-co .up { color: var(--vr-green); } .vr-co .dn { color: var(--vr-red); }
.vr-co .asof { color: var(--vr-muted); font-size: .8rem; }
.vr-co .links { display: flex; gap: 22px; flex-wrap: wrap; margin-top: 10px; font-size: .95rem; }
.vr-co .links a, .vr-co .links span { color: var(--vr-blue-2); font-weight: 600; }
.vr-co .links span.plain { color: var(--vr-ink); }
.vr-co .meta { color: var(--vr-muted); font-size: .8rem; margin-top: 10px; }
.vr-co .ind { display: inline-block; font-size: .74rem; font-weight: 600; color: var(--vr-navy); background: var(--vr-cream);
  border: 1px solid var(--vr-line); border-radius: 999px; padding: 2px 10px; margin-right: 6px; }

/* ratio grid like Screener's top box */
.vr-ratios { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border: 1px solid var(--vr-line);
  border-radius: 12px; background: #fff; overflow: hidden; }
@media (max-width: 900px) { .vr-ratios { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.vr-ratios .c { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; padding: 12px 18px;
  border-bottom: 1px solid var(--vr-line-2); }
.vr-ratios .c:nth-child(6n+4), .vr-ratios .c:nth-child(6n+5), .vr-ratios .c:nth-child(6n+6) { background: #FBF8F5; }
.vr-ratios .n { color: #5F6B7A; font-size: .92rem; }
.vr-ratios .v { color: var(--vr-ink); font-weight: 700; font-size: 1rem; white-space: nowrap; }
.vr-ratios .v small { color: var(--vr-muted); font-weight: 500; }
.sis-grid { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 12px; }
.sis-ratio { border: 1px solid var(--vr-line); border-radius: 10px; padding: 12px 14px; background: #fff; }
.sis-ratio .n { font-size: .7rem; letter-spacing: .06em; color: var(--vr-muted); font-weight: 700; text-transform: uppercase; }
.sis-ratio .v { font-size: 1.15rem; font-weight: 700; margin: 4px 0 2px 0; color: var(--vr-navy); }
.sis-ratio .u { font-size: .68rem; color: #8C8C8C; }

/* stat tiles */
.vr-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
.vr-tile { background: #fff; border: 1px solid var(--vr-line); border-radius: 12px; padding: 14px 16px; box-shadow: var(--vr-shadow); }
.vr-tile .l { font-size: .72rem; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--vr-muted); }
.vr-tile .v { font-size: 1.35rem; font-weight: 700; color: var(--vr-navy); margin-top: 4px; white-space: nowrap; }
.vr-tile .v.up { color: var(--vr-green); } .vr-tile .v.dn { color: var(--vr-red); }
.vr-tile .h { font-size: .76rem; color: var(--vr-muted); margin-top: 2px; }

/* ------------------------------------------------------------ tables */
.sis-tablewrap { overflow-x: auto; border: 1px solid var(--vr-line); border-radius: 10px; background: #fff; }
table.sis-table { border-collapse: collapse; width: 100%; font-size: .86rem; }
table.sis-table th { background: #FBF8F5; color: var(--vr-navy); font-weight: 700; text-align: right;
  padding: 10px 14px; white-space: nowrap; border-bottom: 1px solid var(--vr-line); font-size: .8rem; }
table.sis-table th:first-child, table.sis-table td:first-child { text-align: left; position: sticky; left: 0;
  background: #fff; z-index: 1; border-right: 1px solid var(--vr-line-2); min-width: 180px; }
table.sis-table th:first-child { background: #FBF8F5; }
table.sis-table td { padding: 9px 14px; text-align: right; white-space: nowrap; border-bottom: 1px solid var(--vr-line-2);
  color: var(--vr-ink); font-variant-numeric: tabular-nums; }
table.sis-table td:first-child { font-weight: 500; }
table.sis-table tbody tr:hover td { background: #FFF8F3; }
table.sis-table tr.bold td { font-weight: 700; }
table.sis-table tr.sub td { color: var(--vr-muted); font-size: .8rem; background: #FDFCFB; }
table.sis-table tr.sub td:first-child { padding-left: 30px; background: #FDFCFB; }
table.sis-table .plus { color: var(--vr-blue); font-weight: 800; }
table.sis-table .up { color: var(--vr-green); font-weight: 700; } table.sis-table .dn { color: var(--vr-red); font-weight: 700; }
table.sis-table.wrap td { white-space: normal; text-align: left; }
table.sis-table.wrap th { text-align: left; }
table.sis-table.wrap td.val { font-weight: 700; white-space: nowrap; }
table.sis-table.left td, table.sis-table.left th { text-align: left; }

.sis-unit { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 2px 0 8px 0; font-size: .78rem; color: var(--vr-muted); }
.sis-unit b { background: var(--vr-orange-soft); color: #8A5200; border: 1px solid #FFD79A; padding: 2px 10px;
  border-radius: 999px; font-weight: 700; white-space: nowrap; }
.sis-src { font-size: .72rem; font-weight: 700; padding: 2px 9px; border-radius: 999px; background: var(--vr-blue-soft);
  color: var(--vr-blue); white-space: nowrap; }
.vr-badge { display: inline-block; font-size: .7rem; font-weight: 700; padding: 2px 9px; border-radius: 999px;
  letter-spacing: .03em; white-space: nowrap; }
.vr-badge.text { background: var(--vr-blue-soft); color: var(--vr-blue); }
.vr-badge.outlook { background: var(--vr-green-soft); color: var(--vr-green); }
.vr-badge.action { background: var(--vr-orange-soft); color: #8A5200; }
.vr-badge.activity { background: #F1F1F1; color: #555; }

/* compounded growth: two boxes per row */
.vr-growth-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
@media (max-width: 700px) { .vr-growth-grid { grid-template-columns: 1fr; } }
.vr-growth { background: #fff; border: 1px solid var(--vr-line); border-radius: 10px; overflow: hidden;
  box-shadow: var(--vr-shadow); }
.vr-growth .h { font-weight: 700; color: var(--vr-navy); font-size: .9rem; padding: 10px 16px; background: #FBF8F5;
  border-bottom: 1px solid var(--vr-line); text-transform: uppercase; letter-spacing: .04em; }
table.sis-table.compact th:first-child, table.sis-table.compact td:first-child { position: static; min-width: 0;
  border-right: none; }
table.sis-table.compact th { background: #fff; }
table.sis-table.compact td:last-child, table.sis-table.compact th:last-child { text-align: right; font-weight: 700; }

/* ------------------------------------------------------------ report */
.sis-note { border-left: 3px solid var(--vr-orange); background: var(--vr-orange-soft); color: #6B4100; padding: 10px 14px;
  font-size: .8rem; border-radius: 8px; margin-top: 8px; }
.sis-badge { display: inline-block; padding: 5px 14px; border-radius: 999px; font-weight: 800; font-size: .78rem;
  color: #fff; letter-spacing: .06em; }
.sis-Positive { background: var(--vr-green); } .sis-Neutral { background: var(--vr-amber); } .sis-Cautious { background: var(--vr-red); }
.sis-banner { background: var(--vr-blue); color: #fff; padding: 13px 18px; border-radius: 10px; font-weight: 700;
  font-size: 1.04rem; margin: 12px 0; line-height: 1.45; }
.sis-summary { background: var(--vr-cream); border-left: 4px solid var(--vr-orange); padding: 13px 18px; border-radius: 8px;
  line-height: 1.7; color: var(--vr-text); }
.sis-doc ul { padding-left: 18px; margin: 0; } .sis-doc li { margin-bottom: 8px; font-size: .88rem; }
.sis-doc .d { color: var(--vr-muted); font-size: .76rem; }
.sis-doc h4 { color: var(--vr-navy) !important; }
.sis-list { list-style: none; padding: 0; margin: 0; }
.sis-list li { padding: 8px 0 8px 26px; position: relative; border-bottom: 1px dashed var(--vr-line); font-size: .9rem; }
.sis-list li::before { content: "✓"; position: absolute; left: 4px; top: 8px; color: var(--vr-green); font-weight: 800; }
.sis-list.risk li::before { content: "!"; color: var(--vr-red); left: 8px; }
.sis-list.watch li::before { content: "›"; color: var(--vr-blue); left: 8px; font-size: 1.1rem; top: 5px; }

/* empty state */
.sis-empty { text-align: center; padding: 34px 20px; border: 1.5px dashed #D9CFC3; border-radius: 14px; background: #fff; }
.sis-empty .big { font-size: 1.12rem; font-weight: 700; color: var(--vr-navy); }
.sis-empty .small { color: var(--vr-muted); margin-top: 6px; font-size: .9rem; }
.sis-steps { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-top: 16px; text-align: left; }
.sis-steps div { background: var(--vr-cream); border: 1px solid var(--vr-line); border-radius: 10px; padding: 12px; font-size: .86rem; }
.sis-steps b { color: var(--vr-blue); display: block; margin-bottom: 4px; }

/* news */
.sis-news, .vr-news { padding: 12px 16px; border-bottom: 1px solid var(--vr-line-2); background: #fff; }
.vr-newslist { border: 1px solid var(--vr-line); border-radius: 12px; background: #fff; overflow: hidden; box-shadow: var(--vr-shadow); }
.vr-news:last-child { border-bottom: none; }
.vr-news .src, .sis-news .src { display: inline-block; font-size: .72rem; font-weight: 700; color: var(--vr-blue);
  background: var(--vr-blue-soft); border-radius: 4px; padding: 1px 7px; margin-right: 8px; }
.vr-news a, .sis-news a { font-weight: 600; color: var(--vr-ink); font-size: .95rem; }
.vr-news a:hover, .sis-news a:hover { color: var(--vr-blue); }
.vr-news .meta, .sis-news .meta { color: var(--vr-muted); font-size: .76rem; margin-top: 3px; }
.vr-srchead { font-weight: 700; color: var(--vr-navy); font-size: .95rem; padding: 10px 16px; background: #FBF8F5;
  border-bottom: 1px solid var(--vr-line); }

/* ------------------------------------------------------------ auth page */
.vr-auth-brand { background: var(--vr-blue); color: #fff; border-radius: 16px; padding: 36px 32px; min-height: 520px;
  box-shadow: 0 14px 36px rgba(28,77,160,.25); position: relative; overflow: hidden; }
.vr-auth-brand::after { content: ""; position: absolute; right: -70px; bottom: -70px; width: 240px; height: 240px;
  border-radius: 50%; background: rgba(255,164,28,.25); }
.vr-auth-brand .logo { display: flex; align-items: center; gap: 12px; }
.vr-auth-brand .logo .mark { width: 44px; height: 44px; border-radius: 10px; background: #fff; color: var(--vr-blue);
  display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 1.2rem; }
.vr-auth-brand .logo .n { font-size: 1.6rem; font-weight: 800; color: #fff; line-height: 1.1; }
.vr-auth-brand .tag { color: #DCE6F7; margin: 14px 0 26px 0; font-size: 1rem; line-height: 1.6; }
.vr-auth-brand .feat { display: flex; gap: 12px; margin-bottom: 16px; align-items: flex-start; position: relative; z-index: 1; }
.vr-auth-brand .ic { width: 28px; height: 28px; border-radius: 8px; background: var(--vr-orange); color: #1B1B1B;
  display: flex; align-items: center; justify-content: center; font-weight: 800; flex: none; font-size: .85rem; }
.vr-auth-brand .ft { font-weight: 700; color: #fff; font-size: .95rem; }
.vr-auth-brand .fd { color: #C9D7F0; font-size: .84rem; }
.vr-auth-title { font-size: 1.6rem; font-weight: 700; color: var(--vr-navy); margin-top: 6px; }
.vr-auth-sub { color: var(--vr-muted); margin-bottom: 6px; }

/* profile */
.vr-avatar { width: 64px; height: 64px; border-radius: 50%; background: var(--vr-blue); color: #fff; font-weight: 800;
  font-size: 1.5rem; display: flex; align-items: center; justify-content: center; }
.vr-prof { display: flex; gap: 18px; align-items: center; }
.vr-prof .n { font-size: 1.35rem; font-weight: 700; color: var(--vr-navy); }
.vr-prof .e { color: var(--vr-muted); }

/* ------------------------------------------------------------ floating chatbot */
.st-key-chat_fab { position: fixed !important; right: 26px; bottom: 24px; z-index: 999990; width: auto !important; }
.st-key-chat_fab button { background: var(--vr-blue) !important; color: #fff !important; border-radius: 999px !important;
  padding: 12px 22px !important; border: none !important; box-shadow: 0 10px 26px rgba(28,77,160,.35) !important; }
.st-key-chat_fab button p { color: #fff !important; font-weight: 700 !important; }
.st-key-chat_fab div[data-testid="stPopoverBody"], div[data-testid="stPopoverBody"]:has(.sis-chat-head) {
  width: 460px !important; max-width: 92vw; }
.sis-chat-head { background: var(--vr-blue); color: #fff; border-radius: 10px; padding: 12px 14px; margin-bottom: 4px; }
.sis-chat-head .a { font-weight: 700; font-size: 1rem; color: #fff; }
.sis-chat-head .b { font-size: .76rem; color: #DCE6F7; }
.vr-foot { color: var(--vr-muted); font-size: .76rem; text-align: center; margin-top: 30px; }
</style>
"""

# Stock Insight Studio

Scrape any NSE company's page from **Screener.in**, show it the same way Screener does, store every number in a **structured Supabase (PostgreSQL) database** you can query later, and generate a **professional, broker-style analysis report** (like the ICICI Securities / Trendlyne reports), with the latest news and a **floating AI chatbot** powered by **RAGFlow**.

The whole project is written in Python.

> Only real scraped data is used. There is no seed or dummy data. The company list comes from NSE's official equity list, all financial numbers come from Screener.in, and news comes from Google News.
>
> **Screener is the main source.** The scrape, the stored data, the scorecard and every financial table use Screener only. When an analysis report is generated, a few figures Screener does not publish are looked up on NSE, Value Research Online, Yahoo Finance, Investing.com and Macrotrends and shown in their own section with the source and a link.

---

## Features

| Area | What you get |
|---|---|
| **Login** | Page 1: sign in, create account, forgot password (Supabase Auth) |
| **Company picker** | A dropdown of every NSE company (about 2,000+), plus a free-text search that also queries Screener's own search (for BSE-only names) |
| **Scraper** | Summary ratios, pros/cons, peers, quarterly results, P&L, compounded growth tables, balance sheet, cash flow, ratios, shareholding (quarterly and yearly), announcements, annual reports, credit ratings, concalls, 5-year price and P/E history, and **all "+" breakdown rows** |
| **Screener-style view** | Cards and tables laid out like Screener, with a toggle for the "+" breakdowns |
| **Exports** | Screener data as **JSON** and as a **PDF** (landscape, every column); analysis report as **JSON** and as a broker-style **PDF** with exhibits |
| **Structured storage** | Every number is stored as one row in `financial_facts` (company · section · metric · period · value · unit), with SQL views for "latest capture" |
| **Analysis report** | Python metrics feed a six-factor scorecard, which gives a stance (Positive / Neutral / Cautious). Gemini writes the narrative using the supplied numbers only. The report includes charts, financial summary tables, peers, news and a disclaimer |
| **Future outlook** | Revenue, net profit and EPS projected for the next three fiscal years and four quarters with **scikit-learn, SciPy and NumPy**: three models, each tested on the company's own past, with a low–high range and a confidence level |
| **Gap filling** | Figures Screener does not publish (for a bank: NIM, NPAs, CASA, capital adequacy; for any company: beta, analyst estimates and so on) are taken from four other websites at report time only, each with source and link |
| **Unit labels** | A green "Unit: ₹ crore" line above every chart and table, on screen and in both PDFs |
| **News** | Company news only, up to 15 headlines per source from the last 90 days: the company's own filings from the **NSE** and **BSE** announcement APIs, plus Economic Times, Moneycontrol, Business Standard, Mint, CNBC-TV18, The Hindu BusinessLine, Financial Express, Business Today, NDTV Profit, Zee Business and Reuters (their RSS feeds plus Google News searches limited to each site, by company name and by NSE symbol). The report prints how many headlines each source gave. A headline is kept only if its title names the company; general market or economy stories are left out of the company page and the report. AI key insights follow. |
| **History** | Fetch history, analysis history (open any past report), and a **"Query stored data"** explorer with CSV export and example SQL |
| **Chatbot** | A floating button at the bottom-right. It answers from a per-company RAGFlow knowledge base that syncs automatically after every fetch, report and news refresh. If RAGFlow is not set up, it falls back to Gemini over the stored data |

## Architecture

```
Streamlit UI (app.py: top bar: 3 tabs + user menu)
 ├─ ui/auth_view.py          sign in / create account / forgot password (Supabase Auth)
 ├─ ui/portfolio_view.py     holdings + watchlist
 ├─ ui/company_view.py       Stocks: search → company page with Screener-style sub-tabs
 ├─ ui/report_view.py        Analysis Report sub-tab (generate, reopen, export)
 ├─ ui/movers_view.py        Market Movers (analysis/market.py)
 ├─ ui/market_news_view.py   Market News (analysis/news.py)
 ├─ ui/notebook_view.py      notes + activity + history (ui/history_view.py)
 ├─ ui/profile_view.py       account, usage, password, system status (ui/status_view.py)
 ├─ ui/styles.py             Value Research colours
 └─ ui/chat_widget.py        floating chatbot (bottom-right)
        │
 core/services.py ── scraper/screener_client.py  (requests → Screener HTML + JSON endpoints)
        │               └─ scraper/parser.py      (BeautifulSoup → normalized payload)
        │
 core/repository.py ── Supabase Postgres (psycopg): companies, scrape_runs, financial_facts,
        │               summary_ratios, peers, company_documents, price_history, news_items,
        │               analysis_reports, chat_messages, rag_sync
        │
 analysis/metrics.py → analysis/scorecard.py → analysis/report.py (Gemini via analysis/llm.py)
        ├─ analysis/forecast.py   projections (scikit-learn, SciPy) from Screener history
        └─ analysis/external.py   gap filling: Yahoo Finance (yfinance) + Gemini with Google Search,
                                  limited to valueresearchonline.com, investing.com, macrotrends.net
 core/units.py   unit label for every table
 exports/pdf_screener.py · exports/pdf_report.py · exports/charts.py (ReportLab + matplotlib)
 rag/documents.py → rag/sync.py → RAGFlow HTTP API (rag/ragflow_client.py) → rag/chat.py
```

**Why the report is not generated by RAG:** retrieval over tables of numbers is unreliable. The report is built from exact calculations, and Gemini only writes the narrative around the supplied numbers. RAGFlow is used where it works best: the chatbot, which is continuously re-synced.

## Quick start

1. **Python 3.10 – 3.12** must be installed.
2. Set up Supabase by following [`docs/SETUP_SUPABASE.md`](docs/SETUP_SUPABASE.md): create the project, copy the keys and the **Session pooler** connection string into `.env`. The app creates missing tables by itself on start (or run `sql/schema.sql` once in the SQL Editor).
3. Get a **Gemini API key** at https://aistudio.google.com/apikey.
4. *(Optional, for the RAG chatbot)* Set up RAGFlow by following [`docs/SETUP_RAGFLOW.md`](docs/SETUP_RAGFLOW.md).
5. Install:
   - **Windows:** double-click `setup_windows.bat`
   - **macOS/Linux:** `./setup_unix.sh`
6. Edit `.env` and fill in your values (see `.env.example`).
7. Load the NSE company list. Do **one** of these:
   - run `python -m scripts.load_companies`
   - in the app, go to **Profile → System status** and click **Download & load NSE list**
   - if NSE blocks the download, download `EQUITY_L.csv` in your browser and upload it on the same page
8. Run the app:
   - **Windows:** `run_app.bat`
   - **macOS/Linux:** `streamlit run app.py`
9. Open http://localhost:8501, create an account, open **Stocks** and search a company.

### Test the scraper without a database

```bash
python -m scripts.smoke_test HDFCBANK
```

This writes the JSON and both PDFs for real, live data to `./output`.

## Using the app

The app has a top bar like Screener and colours like Value Research. After signing in you see three tabs (Stocks, Market Movers, Market News); Portfolio, Notebook and Profile open from the user menu (top right):

| Tab | What it does |
|---|---|
| **Portfolio** | Add the shares you own (company, quantity, average price, date). Shows current value, profit or loss and an allocation chart, plus your watchlist. Prices come from Yahoo Finance (delayed); if it cannot be reached, the last Screener close stored for the company is used. Nothing is pre-filled. |
| **Stocks** | Search any NSE company. Stored data opens at once; a company never opened before is fetched from Screener automatically. The company page has Screener-style sub-tabs: **Overview, Chart, Key Ratios, Peers, Quarters, Profit & Loss, Balance Sheet, Cash Flow, Ratios, Shareholding, Documents**, plus a big **📊 Analysis Report** button above them that opens the full report (company news is inside the report; general news is in Market News). Buttons: ☆ Follow, ✎ Add note, Refresh from Screener, Export (JSON, Excel, PDF). |
| **Market Movers** | Top gainers, top losers, stocks at a 52-week high and most active stocks, from NSE's live data. If NSE blocks the request, the lists are calculated from Yahoo Finance prices for the Nifty 100, and the page says so. |
| **Market News** | Latest general stock-market headlines from the 11 news websites above, with search, a website filter and an AI summary of key points. |
| **Notebook** | Your notes (text note, outlook, action) and an automatic activity log (fetches, reports, watchlist and portfolio changes), plus fetch history, report history and the stored-data explorer. Everything is saved in Supabase, so it is there at every sign-in. |
| **Profile** | Name, email, member since, usage figures, change name or password, system status (database, Gemini, RAGFlow, NSE company list) and sign out. |

**Key Ratios** shows Screener's ratios, ratios calculated from Screener's statements, and a separate block of figures Screener does not publish, from Yahoo Finance, Value Research Online, Investing.com and Macrotrends. Each has its source and link, and the lookup is saved in `external_data` and reused for 24 hours.

**Analysis Report** works as before (scorecard, projections, exhibits, PDF), and now also has a **peer comparison table** and a stronger **news section**: headlines that name the company, grouped by source (NSE and BSE filings first, then 11 news websites: Economic Times, Moneycontrol, Business Standard, Mint, CNBC-TV18, The Hindu BusinessLine, Financial Express, Business Today, NDTV Profit, Zee Business, Reuters — up to 15 headlines from each), then **Key insights from the news**, then the company's exchange announcements.

**Chatbot:** click the blue **💬 Ask about SYMBOL** button at the bottom-right.

## Querying the stored data (SQL)

```sql
-- Net profit by quarter, latest capture of every company
select nse_symbol, period_label, value
from v_latest_facts
where section = 'quarters' and metric = 'Net Profit' and parent_metric is null
order by nse_symbol, period_date;

-- 5-year sales CAGR league table
select nse_symbol, value from v_latest_facts
where section = 'growth' and metric = 'Compounded Sales Growth' and period_label = '5 Years'
order by value desc;

-- Every capture of a company over time (history is never overwritten)
select id, basis, started_at, latest_period from scrape_runs
where company_id = (select id from companies where nse_symbol = 'TCS') order by started_at desc;
```

Sections stored: `quarters`, `profit-loss`, `balance-sheet`, `cash-flow`, `ratios`, `shareholding-quarterly`, `shareholding-yearly`, `growth`. Breakdown rows have `parent_metric` set (for example, parent `Expenses` → `Employee Cost %`).

## How the scorecard works

Each factor is scored 0–10 from the data, then weighted to give a total out of 100.

| Factor | Weight | Based on |
|---|---|---|
| Growth | 20 | 5-year revenue and profit CAGR, with a penalty if TTM profit growth is negative |
| Profitability | 20 | ROE (plus ROCE for non-financials) |
| Balance sheet | 15 | Debt/equity; for banks and NBFCs, assets/net worth |
| Cash flow quality | 15 | 5-year cumulative CFO ÷ net profit (neutral for lenders) |
| Valuation | 15 | P/E compared with the company's own 5-year median and with the peer median |
| Momentum & ownership | 15 | Price vs 200-DMA, 1-year return, change in FII+DII and promoter holding |

The stance is **Positive** at 65 or above, **Neutral** from 45 up to 65, and **Cautious** below 45. It is mechanical: there is no buy/sell call and no target price.

## Units

Screener reports rupee amounts in **₹ crore** (1 crore = 1,00,00,000 = 10 million; 1 lakh crore = 1 trillion). Every chart and table carries a green unit line, for example `Unit: ₹ crore · EPS in ₹ per share`. PDF charts scale large amounts and say so (`₹ thousand crore`, `₹ lakh crore`). The labels live in `core/units.py`.

## How the projections work

`analysis/forecast.py` projects revenue, net profit and EPS from the history Screener shows. Nothing from other websites goes into it.

1. Work on logarithms, because growth compounds.
2. Detect a one-off jump (a merger, for example) and treat it as a level shift so it does not inflate the growth rate.
3. Fit three models: a robust trend (`sklearn.linear_model.HuberRegressor`, recent years weighted more), damped Holt exponential smoothing (parameters found with `scipy.optimize.minimize`), and a fading-momentum model. Quarterly series add a same-quarter-last-year model.
4. Walk-forward test: project past years using only the data available before them and measure the error.
5. Weight the models by that accuracy. The weighted average is the **base case**.
6. Turn the test errors into an 80% **low–high range**, and into a **confidence** level (average error below 8% = High, 8–18% = Medium, above 18% = Low).

The report shows the chart, the yearly and quarterly tables, P/E on projected EPS, the reliability table and each model's weight. These are extensions of past figures. They know nothing about management plans, interest rates, regulation or one-off events.

## Google TimesFM AI forecast (in the analysis report)

[TimesFM](https://github.com/google-research/timesfm) is Google Research's pre-trained time-series forecasting model.
For the company you open, the report shows:

- a **"TimesFM AI forecast" table** (by fiscal year and for the next four quarters): TimesFM's own forecast of revenue,
  net profit and EPS, its 10%–90% range (from the model's quantiles), and the base case of all models next to it;
- a **dotted green TimesFM line** on the projection chart;
- TimesFM as one of the models in the weighted base case, tested on the company's past years like the others
  (its weight and past test error are in the table).

Setup: `setup_windows.bat` installs it (`pip install "timesfm[torch]"`, downloads PyTorch). `TIMESFM_ENABLED=true` is
the default. The first report downloads the model weights from Hugging Face (about 1 GB) and is slower; later reports
are fast. If TimesFM is not installed, the report still works and says so in the TimesFM section.
Profile → System status shows whether it loaded. Optional `.env`: `TIMESFM_CHECKPOINT`, `TIMESFM_DEVICE=cuda`.

The default checkpoint `google/timesfm-2.5-200m-pytorch` has Apache-2.0 weights. TimesFM 3.0 weights are for
non-commercial use only. With 10–12 yearly figures per company TimesFM has little history to read, so treat it as one
more opinion, not the answer.

## Data from other websites

| Website | How it is read | Typical use |
|---|---|---|
| NSE | NSE's official quote data (same requests the nseindia.com quote page makes) | Sector P/E, delivery %, free float, impact cost, margin rate, price band, 52-week high/low dates, F&O status, NSE industry |
| Yahoo Finance | `yfinance` library, ticker `SYMBOL.NS` (falls back to `BSECODE.BO`) | Beta, forward P/E and EPS, analyst estimates and targets, return on assets |
| Value Research Online | Its public stock page is read directly (page found once by web search, checked against the NSE/BSE code, saved; you can also paste it on Key Ratios). Gemini search adds anything else | VR quality / growth / valuation / momentum scores, industry P/E, EV/EBITDA, P/B, peer-median P/E and P/B, returns vs Sensex and sector, year-end P/E–P/B history; bank ratios |
| Investing.com | Gemini with Google Search, limited to this site | Ratios Screener does not show |
| Macrotrends | Gemini with Google Search, limited to this site | Long-term ratios, mostly for companies that also trade in the US |

Rules the code follows:

- The **scrape is unchanged**: `scraper/` talks to Screener only, and nothing from these sites is written to the Screener tables.
- Lookups happen **only when a report is generated**, and only for a gap list (`find_gaps` in `analysis/external.py`) plus up to three extra points Gemini judges important.
- A field Screener already has is never taken from elsewhere.
- Each value keeps its **source and link**, is shown under "Additional data from other websites", and is **not part of the scorecard**.
- `EXTERNAL_STRICT=true` (default) keeps an AI-searched value only if Google Search really returned a page from that website. Values from any other website are discarded.
- If a site or the AI lookup fails, the report is still produced and a note says what was missed.
- Untick **Fill gaps from other websites** before generating, or set `EXTERNAL_SOURCES_ENABLED=false`, for a Screener-only report.

The three AI-searched sites block direct scraping, which is why they are read through Google Search. Their figures can be older than Screener's or defined differently, so open the link before relying on one.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Cannot connect to the Supabase database` / `ConnectionTimeout` | `DATABASE_URL` must be the **Session pooler** string (`postgres.<ref>@aws-…pooler.supabase.com:5432`), not `db.<ref>.supabase.co`, which is IPv6-only. Also check the password and that the project is not paused. |
| Sign-up says to confirm your email | Confirm it from your inbox, or turn off *Confirm email* in Supabase (Authentication → Sign In / Providers → Email). |
| NSE list download fails | Download `EQUITY_L.csv` in your browser, then upload it on **System status**, or run `python -m scripts.load_companies --csv path`. |
| Screener returns HTTP 429/403 | Wait a few minutes. You can also raise `SCRAPER_DELAY_SECONDS`, or untick "+ breakdown rows" so fewer requests are made. |
| The report says `rule-based` | `GEMINI_API_KEY` is missing or the call failed. The reason appears as a warning in the app. |
| "Additional data" shows only links | Yahoo rate-limited the request, or Gemini is not configured or found nothing on the approved sites. The note under the section gives the reason. Try again later. |
| Projection confidence is Low | The company has a short or very uneven history, so past tests were inaccurate. Read the range, not the single number. |
| `No module named 'sklearn'` or `'yfinance'` | Run `pip install -r requirements.txt` again inside the virtual environment (`setup_windows.bat` does this). |
| "Notebook / Portfolio tables are missing" | Restart the app (it creates missing tables on start) or run `sql/schema.sql` once in the Supabase SQL Editor. |
| Market Movers says "Yahoo Finance … Nifty 100" | NSE refused the live request (it often blocks scripts). The lists are then calculated from Yahoo Finance end-of-day prices. Try Refresh later. |
| A news website shows no headlines | Its RSS feed did not answer; the Google News search for that site still runs. Market News → "Feeds that did not answer" lists them. |
| Chatbot says "Gemini over stored data" | RAGFlow is off or still indexing. Check **System status → Sync this company now**. |

## Legal and usage notes

- Screener.in's terms restrict automated scraping. This tool fetches only on demand, rate-limits its requests, and is intended for **personal and educational use**. For commercial or public use, get a licensed data feed.
- Yahoo Finance, Value Research Online, Investing.com and Macrotrends each have their own terms of use. The app takes a handful of figures per report, on demand, and always shows the source. The same personal and educational limit applies.
- Projections are statistical estimates. Analyst targets and ratings quoted from other websites are those analysts' views.
- Reports are AI-assisted, are **not investment advice**, and are not SEBI research reports. Every PDF includes a disclaimer.
- The bundled DejaVu fonts (for the ₹ symbol in PDFs) are under the license in `assets/fonts/DejaVu-LICENSE.txt`.

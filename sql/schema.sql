-- =====================================================================
-- Stock Insight Studio - Supabase / PostgreSQL schema
-- Run this once in Supabase: SQL Editor -> New query -> paste -> Run
-- (the app also runs it by itself on start when tables are missing)
-- Safe to re-run (uses IF NOT EXISTS).
-- =====================================================================

-- ---------- Users (mirror of auth.users for app-level joins) ----------
create table if not exists public.profiles (
    id          uuid primary key,              -- = auth.users.id
    email       text not null,
    full_name   text,
    created_at  timestamptz not null default now(),
    last_login  timestamptz
);

-- ---------- Company master (NSE list + Screener identifiers) ----------
create table if not exists public.companies (
    id                     bigserial primary key,
    nse_symbol             text unique,          -- e.g. HDFCBANK (null for BSE-only companies found via Screener search)
    screener_slug          text unique,          -- path part used on screener: /company/<slug>/
    name                   text not null,
    isin                   text,
    series                 text,
    listing_date           date,
    face_value             numeric,
    screener_company_id    bigint,
    screener_warehouse_id  bigint,
    bse_code               text,
    website                text,
    broad_sector           text,
    sector                 text,
    broad_industry         text,
    industry               text,
    source                 text not null default 'NSE_EQUITY_L',
    created_at             timestamptz not null default now(),
    updated_at             timestamptz not null default now()
);
create index if not exists idx_companies_name on public.companies (lower(name));

-- ---------- One row per scrape (fetch history) ----------
create table if not exists public.scrape_runs (
    id              bigserial primary key,
    company_id      bigint not null references public.companies(id) on delete cascade,
    user_id         uuid references public.profiles(id) on delete set null,
    basis           text not null check (basis in ('consolidated','standalone')),
    source_url      text not null,
    status          text not null default 'running' check (status in ('running','success','failed')),
    error           text,
    parser_version  text,
    latest_period   date,
    started_at      timestamptz not null default now(),
    finished_at     timestamptz,
    duration_ms     integer,
    payload         jsonb            -- complete normalized document (used to re-render / export exactly as fetched)
);
create index if not exists idx_runs_company on public.scrape_runs (company_id, basis, started_at desc);
create index if not exists idx_runs_user on public.scrape_runs (user_id, started_at desc);

-- ---------- Long-format fact table: one row = one number ----------
-- section: quarters | profit-loss | balance-sheet | cash-flow | ratios |
--          shareholding-quarterly | shareholding-yearly | growth
create table if not exists public.financial_facts (
    id              bigserial primary key,
    run_id          bigint not null references public.scrape_runs(id) on delete cascade,
    company_id      bigint not null references public.companies(id) on delete cascade,
    basis           text not null,
    section         text not null,
    metric          text not null,
    parent_metric   text,             -- set for "+" breakdown rows (e.g. parent 'Expenses')
    period_label    text not null,    -- 'Jun 2025', 'Mar 2024', 'TTM', '10 Years'
    period_date     date,             -- 2025-06-30 (null for TTM / ranges)
    period_type     text not null,    -- quarter | annual | ttm | range
    value           numeric,
    value_text      text,
    unit            text,             -- INR_CRORE | PERCENT | INR | DAYS | COUNT | RATIO
    row_order       integer
);
create index if not exists idx_facts_lookup on public.financial_facts (company_id, section, metric, period_date);
create index if not exists idx_facts_run on public.financial_facts (run_id);

-- ---------- Top summary ratios (Market cap, P/E, ROE ...) ----------
create table if not exists public.summary_ratios (
    id          bigserial primary key,
    run_id      bigint not null references public.scrape_runs(id) on delete cascade,
    company_id  bigint not null references public.companies(id) on delete cascade,
    name        text not null,
    value       numeric,
    value2      numeric,          -- second number (e.g. Low of High / Low)
    value_text  text,
    unit        text
);
create index if not exists idx_ratios_company on public.summary_ratios (company_id, name);

-- ---------- Peer comparison ----------
create table if not exists public.peers (
    id              bigserial primary key,
    run_id          bigint not null references public.scrape_runs(id) on delete cascade,
    company_id      bigint not null references public.companies(id) on delete cascade,
    rank            integer,
    peer_name       text not null,
    peer_url        text,
    is_median       boolean not null default false,
    metrics         jsonb not null      -- {"CMP Rs.": 735.6, "P/E": 14.35, ...}
);
create index if not exists idx_peers_run on public.peers (run_id);

-- ---------- Documents: announcements, annual reports, credit ratings, concalls ----------
create table if not exists public.company_documents (
    id          bigserial primary key,
    run_id      bigint not null references public.scrape_runs(id) on delete cascade,
    company_id  bigint not null references public.companies(id) on delete cascade,
    doc_type    text not null,    -- announcement | annual_report | credit_rating | concall
    title       text,
    url         text,
    doc_date    timestamptz,
    summary     text,
    extra       jsonb
);
create index if not exists idx_docs_company on public.company_documents (company_id, doc_type);

-- ---------- Daily price history (from Screener price chart API) ----------
create table if not exists public.price_history (
    company_id  bigint not null references public.companies(id) on delete cascade,
    trade_date  date not null,
    close       numeric,
    dma50       numeric,
    dma200      numeric,
    volume      numeric,
    primary key (company_id, trade_date)
);

-- ---------- News ----------
create table if not exists public.news_items (
    id            bigserial primary key,
    company_id    bigint not null references public.companies(id) on delete cascade,
    title         text not null,
    url           text not null,
    source        text,
    published_at  timestamptz,
    summary       text,
    fetched_at    timestamptz not null default now(),
    unique (company_id, url)
);
create index if not exists idx_news_company on public.news_items (company_id, published_at desc);

-- ---------- Analysis reports (analysis history) ----------
create table if not exists public.analysis_reports (
    id            bigserial primary key,
    company_id    bigint not null references public.companies(id) on delete cascade,
    run_id        bigint references public.scrape_runs(id) on delete set null,
    user_id       uuid references public.profiles(id) on delete set null,
    stance        text,           -- Positive | Neutral | Cautious
    score         numeric,        -- 0-100
    model         text,           -- gemini model used or 'rule-based'
    report        jsonb not null, -- full structured report
    created_at    timestamptz not null default now()
);
create index if not exists idx_reports_company on public.analysis_reports (company_id, created_at desc);
create index if not exists idx_reports_user on public.analysis_reports (user_id, created_at desc);

-- ---------- Chatbot history ----------
create table if not exists public.chat_messages (
    id          bigserial primary key,
    user_id     uuid references public.profiles(id) on delete cascade,
    company_id  bigint references public.companies(id) on delete cascade,
    role        text not null check (role in ('user','assistant')),
    content     text not null,
    created_at  timestamptz not null default now()
);
create index if not exists idx_chat_user_company on public.chat_messages (user_id, company_id, created_at);

-- ---------- RAGFlow sync state (one knowledge base + assistant per company) ----------
create table if not exists public.rag_sync (
    company_id      bigint primary key references public.companies(id) on delete cascade,
    dataset_id      text,
    chat_id         text,
    document_ids    jsonb not null default '{}'::jsonb,   -- {"financials.md": "<doc id>", ...}
    last_run_id     bigint,
    last_report_id  bigint,
    status          text,       -- syncing | parsing | ready | failed
    message         text,
    last_synced_at  timestamptz
);

-- =====================================================================
-- Convenience views for easy querying
-- =====================================================================

-- Latest successful run per company + basis
create or replace view public.v_latest_runs as
select distinct on (r.company_id, r.basis)
       r.id as run_id, r.company_id, c.nse_symbol, c.name, r.basis, r.started_at, r.latest_period
from public.scrape_runs r
join public.companies c on c.id = r.company_id
where r.status = 'success'
order by r.company_id, r.basis, r.started_at desc;

-- Facts from the latest successful run only
create or replace view public.v_latest_facts as
select f.*, lr.nse_symbol, lr.name as company_name
from public.financial_facts f
join public.v_latest_runs lr on lr.run_id = f.run_id;

-- =====================================================================
-- Notebook, watchlist, portfolio and data from other websites
-- =====================================================================

-- ---------- Notebook: the user's own notes + automatic activity log ----------
create table if not exists public.user_notes (
    id          bigserial primary key,
    user_id     uuid not null references public.profiles(id) on delete cascade,
    company_id  bigint references public.companies(id) on delete cascade,
    note_type   text not null default 'text' check (note_type in ('text','outlook','action','activity')),
    content     text not null,
    created_at  timestamptz not null default now()
);
create index if not exists idx_notes_user on public.user_notes (user_id, created_at desc);

-- ---------- Watchlist (companies the user follows) ----------
create table if not exists public.watchlist (
    user_id     uuid not null references public.profiles(id) on delete cascade,
    company_id  bigint not null references public.companies(id) on delete cascade,
    added_at    timestamptz not null default now(),
    primary key (user_id, company_id)
);

-- ---------- Portfolio holdings entered by the user ----------
create table if not exists public.portfolio_holdings (
    id          bigserial primary key,
    user_id     uuid not null references public.profiles(id) on delete cascade,
    company_id  bigint not null references public.companies(id) on delete cascade,
    quantity    numeric not null check (quantity > 0),
    avg_price   numeric not null check (avg_price > 0),
    buy_date    date,
    created_at  timestamptz not null default now()
);
create index if not exists idx_holdings_user on public.portfolio_holdings (user_id);

-- ---------- Figures from other websites (Yahoo Finance, Value Research ...) ----------
-- One row per lookup. Screener data stays in its own tables; this is a separate cache.
create table if not exists public.external_data (
    id          bigserial primary key,
    company_id  bigint not null references public.companies(id) on delete cascade,
    fetched_at  timestamptz not null default now(),
    data        jsonb not null
);
create index if not exists idx_external_company on public.external_data (company_id, fetched_at desc);


-- ---------- Pages of this company on other websites (e.g. its Value Research stock page) ----------
create table if not exists public.company_links (
    company_id  bigint not null references public.companies(id) on delete cascade,
    site        text not null,
    url         text not null,
    found_by    text,                         -- search / ai / user
    found_at    timestamptz not null default now(),
    primary key (company_id, site)
);

-- =====================================================================
-- Row Level Security
-- The Streamlit app connects with the database connection string (server side),
-- which bypasses RLS. RLS below protects the tables if anyone uses the public
-- anon key through the Supabase REST API.
-- =====================================================================
alter table public.profiles           enable row level security;
alter table public.companies          enable row level security;
alter table public.scrape_runs        enable row level security;
alter table public.financial_facts    enable row level security;
alter table public.summary_ratios     enable row level security;
alter table public.peers              enable row level security;
alter table public.company_documents  enable row level security;
alter table public.price_history      enable row level security;
alter table public.news_items         enable row level security;
alter table public.analysis_reports   enable row level security;
alter table public.chat_messages      enable row level security;
alter table public.rag_sync           enable row level security;
alter table public.user_notes         enable row level security;
alter table public.watchlist          enable row level security;
alter table public.portfolio_holdings enable row level security;
alter table public.external_data      enable row level security;
alter table public.company_links      enable row level security;

do $$
begin
  -- only on Supabase (plain PostgreSQL has no 'authenticated' role or auth.uid())
  if not exists (select 1 from pg_roles where rolname = 'authenticated')
     or to_regprocedure('auth.uid()') is null then
    return;
  end if;
  -- market data is readable by any signed-in user
  if not exists (select 1 from pg_policies where policyname = 'read_companies') then
    create policy read_companies on public.companies for select to authenticated using (true);
  end if;
  if not exists (select 1 from pg_policies where policyname = 'read_facts') then
    create policy read_facts on public.financial_facts for select to authenticated using (true);
  end if;
  if not exists (select 1 from pg_policies where policyname = 'read_prices') then
    create policy read_prices on public.price_history for select to authenticated using (true);
  end if;
  if not exists (select 1 from pg_policies where policyname = 'read_news') then
    create policy read_news on public.news_items for select to authenticated using (true);
  end if;
  if not exists (select 1 from pg_policies where policyname = 'read_external') then
    create policy read_external on public.external_data for select to authenticated using (true);
  end if;
  if not exists (select 1 from pg_policies where policyname = 'read_links') then
    create policy read_links on public.company_links for select to authenticated using (true);
  end if;
  -- personal data only for its owner
  if not exists (select 1 from pg_policies where policyname = 'own_profile') then
    create policy own_profile on public.profiles for all to authenticated using (id = auth.uid()) with check (id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where policyname = 'own_runs') then
    create policy own_runs on public.scrape_runs for select to authenticated using (user_id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where policyname = 'own_reports') then
    create policy own_reports on public.analysis_reports for select to authenticated using (user_id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where policyname = 'own_chats') then
    create policy own_chats on public.chat_messages for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where policyname = 'own_notes') then
    create policy own_notes on public.user_notes for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where policyname = 'own_watchlist') then
    create policy own_watchlist on public.watchlist for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
  end if;
  if not exists (select 1 from pg_policies where policyname = 'own_holdings') then
    create policy own_holdings on public.portfolio_holdings for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
  end if;
end $$;

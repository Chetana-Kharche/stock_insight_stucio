-- =====================================================================
-- Stock Insight Studio - migration v2 (new UI: notebook, watchlist, portfolio,
-- data from other websites). Run once in Supabase: SQL Editor -> New query -> Run.
-- Safe to re-run. Your existing data is not touched.
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

alter table public.user_notes          enable row level security;
alter table public.watchlist           enable row level security;
alter table public.portfolio_holdings  enable row level security;
alter table public.external_data       enable row level security;

do $$
begin
  -- Supabase only: plain PostgreSQL has no 'authenticated' role or auth.uid(); skip the policies there
  if not exists (select 1 from pg_roles where rolname = 'authenticated')
     or to_regprocedure('auth.uid()') is null then
    return;
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
  if not exists (select 1 from pg_policies where policyname = 'read_external') then
    create policy read_external on public.external_data for select to authenticated using (true);
  end if;
end $$;

-- Accounts (email + password, email code at registration, mobile number on the account), plans and Razorpay.
-- Safe to run many times: the app runs it on every start (only adds what is missing).

-- ---------- Profile: mobile number, username, plan and credits ----------
alter table public.profiles add column if not exists username         text;
alter table public.profiles add column if not exists phone            text;     -- E.164, e.g. +919876543210 (one account per number)
alter table public.profiles add column if not exists phone_verified   boolean not null default false;
alter table public.profiles add column if not exists free_reports_used integer not null default 0;
alter table public.profiles add column if not exists report_credits   integer not null default 0;   -- single-report packs
alter table public.profiles add column if not exists plan             text;     -- monthly | yearly (null = none)
alter table public.profiles add column if not exists plan_expires_at  timestamptz;

alter table public.profiles add column if not exists password_hash    text;     -- pbkdf2-sha256, never the password itself
alter table public.profiles add column if not exists failed_logins    integer not null default 0;
alter table public.profiles add column if not exists locked_until     timestamptz;

create unique index if not exists ux_profiles_phone    on public.profiles (phone) where phone is not null;
create unique index if not exists ux_profiles_username on public.profiles (lower(username)) where username is not null;
create index        if not exists ix_profiles_email    on public.profiles (lower(email));

-- ---------- One-time sign-in codes sent by email (only the hash is stored) ----------
create table if not exists public.otp_codes (
    id          bigserial primary key,
    target      text,                      -- email address the code was sent to
    purpose     text not null check (purpose in ('register','login')),
    code_hash   text,                      -- null when Supabase Auth checks the code itself
    attempts    integer not null default 0,
    used        boolean not null default false,
    expires_at  timestamptz not null,
    created_at  timestamptz not null default now()
);
alter table public.otp_codes add column if not exists target text;
-- the SMS version of this file stored the mobile number in a "phone" column: keep old rows, allow nulls
do $$ begin
    if exists (select 1 from information_schema.columns
               where table_schema = 'public' and table_name = 'otp_codes' and column_name = 'phone') then
        alter table public.otp_codes alter column phone drop not null;
    end if;
end $$;
alter table public.otp_codes drop constraint if exists otp_codes_purpose_check;
alter table public.otp_codes add constraint otp_codes_purpose_check check (purpose in ('register','login','reset'));
create index if not exists ix_otp_target on public.otp_codes (target, created_at desc);

-- ---------- Razorpay payments (one row per payment link) ----------
create table if not exists public.payments (
    id                   bigserial primary key,
    user_id              uuid not null references public.profiles(id) on delete cascade,
    plan_code            text not null check (plan_code in ('single','monthly','yearly')),
    amount_paise         integer not null,
    currency             text not null default 'INR',
    reference_id         text not null unique,       -- our id, sent to Razorpay
    link_id              text unique,                -- plink_...
    short_url            text,
    status               text not null default 'created' check (status in ('created','paid','expired','cancelled','failed')),
    razorpay_payment_id  text,
    created_at           timestamptz not null default now(),
    paid_at              timestamptz,
    applied              boolean not null default false  -- plan/credit already given to the user
);
alter table public.payments add column if not exists callback_login_used boolean not null default false;
create index if not exists ix_payments_user on public.payments (user_id, created_at desc);

-- ---------- Which access paid for each report ----------
create table if not exists public.report_usage (
    id          bigserial primary key,
    user_id     uuid not null references public.profiles(id) on delete cascade,
    report_id   bigint references public.analysis_reports(id) on delete set null,
    source      text not null check (source in ('free','credit','monthly','yearly')),
    created_at  timestamptz not null default now()
);
create index if not exists ix_usage_user on public.report_usage (user_id, created_at desc);

-- =====================================================================
-- Login table for plain PostgreSQL (used when SUPABASE_URL is empty).
-- With Supabase, logins are stored by Supabase Auth instead and this table is not used.
-- Passwords are never stored: only a salted PBKDF2-SHA256 hash.
-- =====================================================================
create table if not exists public.app_users (
    id             uuid primary key default gen_random_uuid(),
    email          text not null unique,
    full_name      text,
    password_hash  text not null,
    created_at     timestamptz not null default now()
);

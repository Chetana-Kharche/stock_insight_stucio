# Using your own PostgreSQL (without Supabase)

The app only needs a PostgreSQL database. Supabase is optional. With a local database:

- All tables are created automatically on the first start (from `sql/schema.sql`).
- Sign-up and sign-in work against the `app_users` table in your database. Passwords are stored only as salted
  PBKDF2-SHA256 hashes, never as plain text.
- What is different: there are no confirmation or reset emails. Forgotten passwords are reset with
  `python scripts/reset_password.py you@example.com`. The data lives on this one computer.

## 1. Install PostgreSQL (Windows)

1. Download the installer from https://www.postgresql.org/download/windows/ (the "EDB" installer), version 16 or 17.
2. Run it and keep the defaults: port **5432**, components *PostgreSQL Server*, *pgAdmin 4*, *Command Line Tools*.
3. When it asks for a password for the `postgres` user, choose one and **write it down**. Using letters and
   digits only is easiest, because `@ : / # %` would need escaping in the URL.
4. Skip Stack Builder at the end.

PostgreSQL now runs as a Windows service and starts with Windows.

## 2. Create the database

**pgAdmin:** open pgAdmin 4 → Servers → PostgreSQL 16 (enter the password) → right-click *Databases* →
*Create → Database…* → name `stock_insight` → Save.

**or PowerShell:**
```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "create database stock_insight"
```

## 3. Edit `.env`

```
DATABASE_URL=postgresql://postgres:YourPassword@localhost:5432/stock_insight
SUPABASE_URL=
SUPABASE_ANON_KEY=
```

Keep the two Supabase lines empty, or delete them. If a `DATABASE_URL` was ever set in Windows environment
variables, remove it, because it would override `.env`.

## 4. Test and start

```powershell
.\.venv\Scripts\activate
python -c "import os,psycopg; from dotenv import load_dotenv; load_dotenv(); psycopg.connect(os.getenv('DATABASE_URL'), connect_timeout=10).close(); print('CONNECTED OK')"
.\run_app.bat
```

On the first start the app creates the tables. Then **Create account** on the login page.
Then load the NSE company list once (Profile → System status → "Download & load NSE list", or `python -m scripts.load_companies`).

## Moving data from Supabase later (optional)

The local database starts empty: companies are fetched from Screener again when you open them. To copy an existing
Supabase database instead, use `pg_dump` on the Supabase Session pooler URL and `psql` to restore into
`stock_insight`. Note that Supabase user accounts are not copied: create your account again.

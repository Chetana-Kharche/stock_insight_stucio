# Supabase setup (about 10 minutes)

## 1. Create the project
1. Go to https://supabase.com and sign in. Click **New project**.
2. **Name:** `stock-insight-studio`. **Region:** *South Asia (Mumbai)* is closest for India.
3. Set a **database password** and save it somewhere. You need it in step 3.
4. Wait until the project finishes provisioning.

## 2. Create the tables
1. In the left menu, open **SQL Editor** and click **New query**.
2. Open `sql/schema.sql` from this project, copy all of it, paste it into the editor, and click **Run**.
3. You should see "Success. No rows returned". Open **Table Editor** and check that these tables exist: `companies`, `scrape_runs`, `financial_facts`, `summary_ratios`, `peers`, `company_documents`, `price_history`, `news_items`, `analysis_reports`, `chat_messages`, `rag_sync` and `profiles`.

The script is safe to run again.

## 3. Copy the keys into `.env`
| `.env` variable | Where to find it |
|---|---|
| `SUPABASE_URL` | **Project Settings → API → Project URL** |
| `SUPABASE_ANON_KEY` | **Project Settings → API → Project API keys → `anon` `public`** |
| `DATABASE_URL` | Click **Connect** at the top of the dashboard → **Connection string** → **Session pooler**. Copy the URI and replace `[YOUR-PASSWORD]` with your database password. |

The Session pooler string looks like this:
```
postgresql://postgres.abcdefghijkl:MyPassword@aws-0-ap-south-1.pooler.supabase.com:5432/postgres
```
Use the Session pooler, not the "Direct connection". On the free plan, the direct connection is IPv6-only and fails on most home networks.

If your password contains special characters such as `@ # / :`, URL-encode them. For example, `@` becomes `%40`.

## 4. Authentication settings
- **Authentication → Sign In / Providers → Email** must be enabled. It is on by default.
- For local development, you can turn **Confirm email** off so that new accounts can log in immediately. If you leave it on, each user must click the link in their confirmation email before they can sign in.
- *(Optional)* **Authentication → URL Configuration → Site URL:** set it to `http://localhost:8501`.

## 5. Load the company master list
From the project folder, with your virtual environment active:
```
python -m scripts.load_companies
```
You can instead use **System status → Download & load NSE list** inside the app. This loads every NSE-listed company from NSE's official `EQUITY_L.csv`.

## Security notes
- The app talks to Postgres on the server side using `DATABASE_URL`, and filters data by the signed-in user.
- Row Level Security is enabled on every table. If someone uses your public `anon` key directly, signed-in users can only read market data and their own history.
- Never commit `.env`. It is already listed in `.gitignore`.

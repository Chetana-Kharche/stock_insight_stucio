# RAGFlow setup (local Docker) for the chatbot

RAGFlow (https://github.com/infiniflow/ragflow) runs as a set of Docker containers: the web UI and API, MySQL, Elasticsearch/Infinity, Redis and MinIO. The app creates **one knowledge base (dataset) and one chat assistant per company**. It pushes these files into the knowledge base:

- `SYMBOL_profile.md`: about the company, summary ratios, pros/cons and peers
- `SYMBOL_financials.md`: every metric of every section, including the "+" breakdowns, shareholding and price history
- `SYMBOL_announcements.md`: announcements, annual reports, credit ratings and concalls
- `SYMBOL_news.md`: the latest headlines
- `SYMBOL_analysis_report.md`: the latest AI-assisted report

These files are re-synced automatically after every fetch, report and news refresh.

## Requirements
- **Docker Desktop** (on Windows, use the WSL 2 backend)
- **16 GB RAM or more**, 4+ CPU cores and about 50 GB of free disk space
- Windows only: set the Elasticsearch memory map limit. Open PowerShell and run:
  ```powershell
  wsl -d docker-desktop -u root sysctl -w vm.max_map_count=262144
  ```
  This must be repeated after each reboot. To make it permanent, add `kernelCommandLine = "sysctl.vm.max_map_count=262144"` under `[wsl2]` in `%UserProfile%\.wslconfig`.

## 1. Start RAGFlow
```bash
git clone https://github.com/infiniflow/ragflow.git
cd ragflow/docker
docker compose -f docker-compose.yml up -d
```
The first start downloads several GB of images. Check progress with:
```bash
docker logs -f docker-ragflow-cpu-1      # the container name may be ragflow-server in older versions
```
Wait until you see the RAGFlow banner, then open **http://localhost** (the web UI runs on port 80).

- **Port 80 already in use?** In `ragflow/docker/.env`, change `SVR_HTTP_PORT` (for example to 8080) and run `docker compose up -d` again.
- The HTTP API is on port **9380**. This is the value for `RAGFLOW_BASE_URL=http://localhost:9380`.

## 2. Configure models (use Gemini)
1. Open http://localhost, **Sign up** (the first account is the admin), and log in.
2. Click your avatar → **Model providers** → find **Gemini** → **Add model**, and paste your Gemini API key.
3. Click **System Model Settings** (or "Set default models"):
   - **Chat model:** `gemini-2.5-flash` (or whichever Gemini model you use)
   - **Embedding model:** keep the built-in default (for example `BAAI/bge-*`), or pick a Gemini embedding model
   - Save.

## 3. Create an API key
Avatar → **API** → **Create new key**. Copy the key (it starts with `ragflow-`).

## 4. Update `.env`
```
RAGFLOW_BASE_URL=http://localhost:9380
RAGFLOW_API_KEY=ragflow-xxxxxxxxxxxxxxxx
RAGFLOW_ENABLED=true
```
Restart the Streamlit app.

## 5. Verify
- In the app, go to **System status**. The RAGFlow card should show **Online**.
- Fetch a company. Within a minute or two, **System status → RAGFlow knowledge base** shows `ready`. You can also click **Sync this company now**.
- In the RAGFlow UI, you will see a dataset named `sis_SYMBOL` and a chat assistant named `sis_chat_SYMBOL`.
- The chatbot caption changes to **Source: RAGFlow knowledge base**.

## Continuous sync
Syncing happens automatically after each fetch, report and news refresh. To sync all companies on a schedule (for example, after running bulk fetches), run:
```bash
python -m scripts.rag_sync_all --loop 15     # every 15 minutes
```

## If RAGFlow is not running
The chatbot keeps working. It answers with **Gemini over the stored database data**: the latest capture, the latest report and news. Set `RAGFLOW_ENABLED=false` to skip RAGFlow entirely.

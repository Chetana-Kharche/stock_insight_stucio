#!/usr/bin/env bash
# One-time setup on macOS / Linux
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
echo "Setup done. Edit .env, then run:  source .venv/bin/activate && streamlit run app.py"

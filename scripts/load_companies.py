"""Load all NSE-listed companies into Supabase.

Usage (from the project root):
    python -m scripts.load_companies                 # download from NSE
    python -m scripts.load_companies --sme           # also include NSE SME (Emerge) companies
    python -m scripts.load_companies --csv EQUITY_L.csv   # use a CSV you downloaded manually
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.company_list import NSE_EQUITY_URL, load_companies  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="Path to a locally downloaded EQUITY_L.csv")
    ap.add_argument("--sme", action="store_true", help="Also load NSE SME companies")
    args = ap.parse_args()
    try:
        n = load_companies(args.csv, include_sme=args.sme)
    except Exception as e:  # noqa: BLE001
        print(f"Failed: {e}")
        print(f"Tip: download {NSE_EQUITY_URL} in your browser and run with --csv <path>")
        sys.exit(1)
    print(f"Loaded/updated {n} companies.")


if __name__ == "__main__":
    main()

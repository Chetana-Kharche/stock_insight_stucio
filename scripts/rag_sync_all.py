"""Push every company with new data/reports into RAGFlow.

Usage (from the project root):
    python -m scripts.rag_sync_all              # one pass
    python -m scripts.rag_sync_all --loop 15    # keep syncing every 15 minutes
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.sync import sync_all_pending  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, default=0, help="repeat every N minutes")
    args = ap.parse_args()
    while True:
        results = sync_all_pending()
        if not results:
            print("Nothing to sync.")
        for name, res in results:
            print(f"{name}: {res.get('status')} {res.get('message', '')}")
        if not args.loop:
            break
        time.sleep(args.loop * 60)


if __name__ == "__main__":
    main()

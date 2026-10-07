"""Live smoke test: scrape one company from Screener (real data), build the analysis
(rule-based unless GEMINI_API_KEY is set) and write JSON + PDFs to ./output — no database needed.

Usage (from the project root):
    python -m scripts.smoke_test HDFCBANK
    python -m scripts.smoke_test TCS --standalone
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analysis.news import fetch_news  # noqa: E402
from analysis.report import build_report  # noqa: E402
from exports.pdf_report import build_report_pdf  # noqa: E402
from exports.pdf_screener import build_screener_pdf  # noqa: E402
from scraper.screener_client import ScreenerClient  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--standalone", action="store_true")
    ap.add_argument("--no-breakdowns", action="store_true")
    args = ap.parse_args()
    basis = "standalone" if args.standalone else "consolidated"
    out = ROOT / "output"
    out.mkdir(exist_ok=True)

    print(f"Fetching {args.symbol} ({basis}) from Screener…")
    payload = ScreenerClient().fetch_company(args.symbol, basis, include_schedules=not args.no_breakdowns,
                                             progress=lambda m, f: print(f"  {int(f * 100):3d}%  {m}"))
    m = payload["meta"]
    print(f"\n{m['name']} · latest period {m['latest_period']} · sections: {list(payload['sections'])}")
    print("Summary ratios:", {r['name']: r['value_text'] for r in payload['summary_ratios']})
    news = []
    try:
        news = fetch_news(m["name"], m.get("nse_symbol"))
        print(f"News items: {len(news)}")
    except Exception as e:  # noqa: BLE001
        print("News failed:", e)
    report = build_report(payload, news)
    print(f"Stance: {report['stance']} · score {report['score']} · narrative: {report['model']}")
    print("Headline:", report["headline"])

    sym = args.symbol.upper()
    (out / f"{sym}_screener.json").write_text(json.dumps(payload, indent=2, default=str, ensure_ascii=False),
                                              encoding="utf-8")
    (out / f"{sym}_screener.pdf").write_bytes(build_screener_pdf(payload))
    (out / f"{sym}_analysis.json").write_text(json.dumps(report, indent=2, default=str, ensure_ascii=False),
                                              encoding="utf-8")
    (out / f"{sym}_analysis.pdf").write_bytes(build_report_pdf(report, payload))
    print(f"\nWrote files to {out}")


if __name__ == "__main__":
    main()

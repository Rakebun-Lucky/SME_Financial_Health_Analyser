"""
Master pipeline runner.

Runs the full data pipeline end-to-end:
  1. Ingest raw data from yfinance  (src/ingestion/yfinance_fetcher.py)
  2. Compute financial ratios       (src/processing/ratio_calculator.py)
  3. Validate data quality          (src/processing/data_validator.py)

Usage:
    python run_pipeline.py                     # all configured tickers
    python run_pipeline.py --sector technology # one sector only
    python run_pipeline.py --tickers WTC.AX TNE.AX  # specific tickers
    python run_pipeline.py --skip-ingest       # ratios + validation only
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.asx_tickers import ALL_TICKERS, ASX_TICKERS
from config.settings import DATA_PROC
from src.ingestion.yfinance_fetcher import ingest_all
from src.processing.ratio_calculator import build_ratio_dataset
from src.processing.data_validator import validate, filter_passed_tickers
from src.utils.logger import get_logger

import pandas as pd

logger = get_logger("pipeline")


def run(tickers: list[str], skip_ingest: bool = False) -> None:
    start = time.time()
    logger.info(f"Pipeline started — {len(tickers)} tickers")
    logger.info("=" * 60)

    # ── Step 1: Ingestion ─────────────────────────────────────────────
    if not skip_ingest:
        logger.info("STEP 1/3 — Ingesting raw data from yfinance...")
        ingest_report = ingest_all(tickers)
        logger.info(
            f"Ingestion done: {len(ingest_report['success'])} ok, "
            f"{len(ingest_report['failed'])} failed"
        )
        # Only process tickers that ingested successfully
        tickers = ingest_report["success"]
    else:
        logger.info("STEP 1/3 — Skipping ingestion (--skip-ingest flag set)")

    if not tickers:
        logger.error("No tickers to process. Exiting.")
        return

    # ── Step 2: Ratio computation ─────────────────────────────────────
    logger.info("\nSTEP 2/3 — Computing financial ratios...")
    ratios_df = build_ratio_dataset(tickers)

    if ratios_df.empty:
        logger.error("Ratio computation produced no data. Check raw files.")
        return

    # ── Step 3: Validation ────────────────────────────────────────────
    logger.info("\nSTEP 3/3 — Validating data quality...")
    report = validate(ratios_df)

    clean_df = filter_passed_tickers(ratios_df, report)
    out_path = DATA_PROC / "ratios_clean.parquet"
    clean_df.to_parquet(out_path)
    logger.info(f"Clean dataset saved → {out_path}")

    # ── Final summary ─────────────────────────────────────────────────
    elapsed = time.time() - start
    logger.info("\n" + "=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info(f"  Time elapsed : {elapsed:.1f}s")
    logger.info(f"  Raw rows     : {len(ratios_df)}")
    logger.info(f"  Clean rows   : {len(clean_df)}")
    logger.info(f"  Pass rate    : {report['summary']['pass_rate']:.1%}")
    logger.info(f"  Output       : {out_path}")
    logger.info("=" * 60)

    # Print column coverage table
    logger.info("\nColumn coverage (clean dataset):")
    for col, cov in sorted(report["column_coverage"].items(), key=lambda x: -x[1]):
        bar = "█" * int(cov * 20)
        logger.info(f"  {col:<30} {bar:<20} {cov:.0%}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run SME Financial Health data pipeline")
    parser.add_argument("--tickers", nargs="+", default=None,
                        help="Specific tickers to process (e.g. WTC.AX TNE.AX)")
    parser.add_argument("--sector", type=str, default=None,
                        help="Process only one sector (e.g. technology)")
    parser.add_argument("--skip-ingest", action="store_true",
                        help="Skip yfinance ingestion, reuse existing raw data")
    args = parser.parse_args()

    if args.tickers:
        tickers = args.tickers
    elif args.sector:
        tickers = ASX_TICKERS.get(args.sector, [])
        if not tickers:
            print(f"Unknown sector. Options: {list(ASX_TICKERS.keys())}")
            sys.exit(1)
    else:
        tickers = ALL_TICKERS

    run(tickers, skip_ingest=args.skip_ingest)
"""
yfinance ingestion module.

Fetches for each ASX ticker:
  - Historical OHLCV price data
  - Quarterly income statement
  - Quarterly balance sheet
  - Quarterly cash flow statement
  - Company info / metadata

All results saved to data/raw/<ticker>/ as parquet + JSON.
"""

import time
import json
from pathlib import Path
from datetime import datetime, timedelta

import yfinance as yf
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import (
    DATA_RAW, LOOKBACK_YEARS, REQUEST_DELAY_SEC, MAX_RETRIES
)
from src.utils.logger import get_logger, retry

logger = get_logger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────

def _ticker_dir(ticker: str) -> Path:
    """Return and create the raw data directory for a ticker."""
    d = DATA_RAW / ticker.replace(".AX", "").lower()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_parquet(df: pd.DataFrame, path: Path) -> None:
    if df is None or df.empty:
        logger.warning(f"Empty dataframe — skipping save to {path.name}")
        return
    df.to_parquet(path, index=True)
    logger.info(f"  Saved {len(df)} rows → {path.name}")


def _save_json(data: dict, path: Path) -> None:
    with open(path, "w") as f:
        # Serialise non-JSON-native types
        json.dump(
            {k: (str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v)
             for k, v in data.items()},
            f, indent=2
        )
    logger.info(f"  Saved metadata → {path.name}")


# ── Fetchers ──────────────────────────────────────────────────────────────

@retry(max_attempts=MAX_RETRIES, delay=2.0)
def fetch_price_history(ticker: str, years: int = LOOKBACK_YEARS) -> pd.DataFrame:
    """
    Fetch daily OHLCV price history.
    Returns a DataFrame with columns: Open, High, Low, Close, Volume, Dividends, Stock Splits
    """
    end   = datetime.today()
    start = end - timedelta(days=years * 365)
    tk    = yf.Ticker(ticker)
    df    = tk.history(start=start.strftime("%Y-%m-%d"),
                       end=end.strftime("%Y-%m-%d"),
                       auto_adjust=True)
    if df.empty:
        raise ValueError(f"No price data returned for {ticker}")
    df.index = pd.to_datetime(df.index).tz_localize(None)  # strip tz for parquet
    return df


@retry(max_attempts=MAX_RETRIES, delay=2.0)
def fetch_financials(ticker: str) -> dict[str, pd.DataFrame]:
    """
    Fetch quarterly financial statements.
    Returns dict with keys: income_stmt, balance_sheet, cashflow
    """
    tk = yf.Ticker(ticker)
    return {
        "income_stmt":   tk.quarterly_income_stmt,
        "balance_sheet": tk.quarterly_balance_sheet,
        "cashflow":      tk.quarterly_cashflow,
    }


@retry(max_attempts=MAX_RETRIES, delay=2.0)
def fetch_company_info(ticker: str) -> dict:
    """
    Fetch company metadata: sector, industry, market cap, description, etc.
    """
    tk   = yf.Ticker(ticker)
    info = tk.info or {}
    # Keep only the fields we care about
    keep = [
        "longName", "sector", "industry", "country", "currency",
        "marketCap", "enterpriseValue", "fullTimeEmployees",
        "longBusinessSummary", "website", "exchange",
        "trailingPE", "forwardPE", "priceToBook",
        "dividendYield", "payoutRatio",
        "beta", "52WeekChange",
        "totalRevenue", "revenueGrowth",
        "grossMargins", "operatingMargins", "profitMargins",
        "returnOnAssets", "returnOnEquity",
        "totalDebt", "totalCash", "debtToEquity",
        "currentRatio", "quickRatio",
        "freeCashflow", "operatingCashflow",
    ]
    return {k: info.get(k) for k in keep}


# ── Main ingestion function ────────────────────────────────────────────────

def ingest_ticker(ticker: str) -> bool:
    """
    Full ingestion pipeline for one ticker.
    Returns True on success, False on failure.
    """
    logger.info(f"Ingesting {ticker}...")
    out = _ticker_dir(ticker)

    try:
        # 1. Price history
        prices = fetch_price_history(ticker)
        _save_parquet(prices, out / "prices.parquet")

        time.sleep(REQUEST_DELAY_SEC)

        # 2. Financial statements
        stmts = fetch_financials(ticker)
        for name, df in stmts.items():
            if df is not None and not df.empty:
                # Transpose so dates are rows, metrics are columns
                df_t = df.T
                df_t.index = pd.to_datetime(df_t.index).tz_localize(None)
                _save_parquet(df_t, out / f"{name}.parquet")

        time.sleep(REQUEST_DELAY_SEC)

        # 3. Company metadata
        info = fetch_company_info(ticker)
        info["ticker"]      = ticker
        info["fetched_at"]  = datetime.utcnow().isoformat()
        _save_json(info, out / "info.json")

        logger.info(f"  {ticker} done.\n")
        return True

    except Exception as e:
        logger.error(f"  {ticker} FAILED: {e}\n")
        return False


def ingest_all(tickers: list[str]) -> dict:
    """
    Ingest a list of tickers and return a summary report.
    """
    results = {"success": [], "failed": []}
    total   = len(tickers)

    for i, ticker in enumerate(tickers, 1):
        logger.info(f"[{i}/{total}] Processing {ticker}")
        ok = ingest_ticker(ticker)
        if ok:
            results["success"].append(ticker)
        else:
            results["failed"].append(ticker)
        # Polite delay between tickers
        time.sleep(REQUEST_DELAY_SEC)

    logger.info(
        f"\nIngestion complete. "
        f"Success: {len(results['success'])}/{total} | "
        f"Failed: {len(results['failed'])}/{total}"
    )
    if results["failed"]:
        logger.warning(f"Failed tickers: {results['failed']}")

    return results


# ── CLI entry point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from config.asx_tickers import ALL_TICKERS

    parser = argparse.ArgumentParser(description="Ingest ASX financial data via yfinance")
    parser.add_argument(
        "--tickers", nargs="+",
        help="Specific tickers to ingest (default: all configured tickers)",
        default=None,
    )
    parser.add_argument(
        "--sector", type=str,
        help="Ingest only tickers from a specific sector",
        default=None,
    )
    args = parser.parse_args()

    if args.tickers:
        tickers = args.tickers
    elif args.sector:
        from config.asx_tickers import ASX_TICKERS
        tickers = ASX_TICKERS.get(args.sector, [])
        if not tickers:
            print(f"Unknown sector '{args.sector}'. Available: {list(ASX_TICKERS.keys())}")
            sys.exit(1)
    else:
        tickers = ALL_TICKERS

    report = ingest_all(tickers)
    print(f"\nDone. {len(report['success'])} succeeded, {len(report['failed'])} failed.")
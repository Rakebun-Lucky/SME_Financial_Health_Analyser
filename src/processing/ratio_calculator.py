"""
Financial ratio calculator.

Reads raw parquet files for each ticker and computes:
  - Liquidity ratios  (current, quick)
  - Leverage ratios   (debt-to-equity, interest coverage)
  - Profitability     (operating margin, net margin, ROE, ROA)
  - Growth metrics    (revenue YoY, earnings YoY)
  - Valuation         (P/E, P/B, EV/EBITDA)
  - Cash flow quality (FCF yield, FCF to net income)

Output: one row per (ticker, quarter) → data/processed/ratios.parquet
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import DATA_RAW, DATA_PROC
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ── Safe division helper ──────────────────────────────────────────────────

def safe_div(num, den, fill=np.nan):
    """Divide two series element-wise, filling division-by-zero with `fill`."""
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where(den != 0, num / den, fill)
    return result


# ── Load raw data ─────────────────────────────────────────────────────────

def load_ticker_data(ticker: str) -> dict:
    """Load all raw parquet files and info.json for one ticker."""
    d = DATA_RAW / ticker.replace(".AX", "").lower()
    data = {}

    for name in ["income_stmt", "balance_sheet", "cashflow", "prices"]:
        path = d / f"{name}.parquet"
        if path.exists():
            data[name] = pd.read_parquet(path)
        else:
            data[name] = None
            logger.warning(f"  {ticker}: missing {name}.parquet")

    info_path = d / "info.json"
    if info_path.exists():
        with open(info_path) as f:
            data["info"] = json.load(f)
    else:
        data["info"] = {}

    return data


# ── Ratio computation ─────────────────────────────────────────────────────

def compute_ratios(ticker: str, data: dict) -> pd.DataFrame | None:
    """
    Compute financial ratios for one ticker.
    Returns a DataFrame indexed by quarter date, or None if data insufficient.
    """
    inc  = data.get("income_stmt")
    bal  = data.get("balance_sheet")
    cf   = data.get("cashflow")
    info = data.get("info", {})

    if inc is None or bal is None or inc.empty or bal.empty:
        logger.warning(f"  {ticker}: insufficient statement data — skipping")
        return None

    # Align on common quarterly index
    idx = inc.index.intersection(bal.index)
    if cf is not None and not cf.empty:
        idx = idx.intersection(cf.index)
    if len(idx) < 2:
        logger.warning(f"  {ticker}: only {len(idx)} aligned quarters — skipping")
        return None

    inc  = inc.loc[idx].sort_index()
    bal  = bal.loc[idx].sort_index()
    cf   = cf.loc[idx].sort_index() if (cf is not None and not cf.empty) else None

    rows = []
    for date in idx:
        i  = inc.loc[date]
        b  = bal.loc[date]
        c  = cf.loc[date]  if cf  is not None else pd.Series(dtype=float)

        # ── Liquidity ──────────────────────────────────────────────────
        current_assets  = b.get("Current Assets",  np.nan)
        current_liabs   = b.get("Current Liabilities", np.nan)
        inventory       = b.get("Inventory",        0)
        cash            = b.get("Cash And Cash Equivalents", np.nan)

        current_ratio   = safe_div(current_assets, current_liabs)
        quick_ratio     = safe_div(current_assets - inventory, current_liabs)
        cash_ratio      = safe_div(cash, current_liabs)

        # ── Leverage ───────────────────────────────────────────────────
        total_debt      = b.get("Total Debt", b.get("Long Term Debt", np.nan))
        total_equity    = b.get("Stockholders Equity", np.nan)
        total_assets    = b.get("Total Assets", np.nan)
        ebit            = i.get("EBIT", i.get("Operating Income", np.nan))
        interest_exp    = abs(i.get("Interest Expense", np.nan) or np.nan)

        debt_to_equity  = safe_div(total_debt, total_equity)
        debt_to_assets  = safe_div(total_debt, total_assets)
        equity_ratio    = safe_div(total_equity, total_assets)
        interest_cover  = safe_div(ebit, interest_exp)

        # ── Profitability ──────────────────────────────────────────────
        revenue         = i.get("Total Revenue", np.nan)
        gross_profit    = i.get("Gross Profit",  np.nan)
        operating_inc   = i.get("Operating Income", np.nan)
        net_income      = i.get("Net Income",    np.nan)

        gross_margin    = safe_div(gross_profit,  revenue) * 100
        operating_margin= safe_div(operating_inc, revenue) * 100
        net_margin      = safe_div(net_income,    revenue) * 100
        roe             = safe_div(net_income, total_equity) * 100
        roa             = safe_div(net_income, total_assets) * 100

        # ── Cash flow quality ──────────────────────────────────────────
        op_cashflow     = c.get("Operating Cash Flow",  np.nan) if len(c) else np.nan
        capex           = abs(c.get("Capital Expenditure", 0) or 0) if len(c) else np.nan
        fcf             = op_cashflow - capex if not (np.isnan(op_cashflow) or np.isnan(capex)) else np.nan
        fcf_margin      = safe_div(fcf, revenue) * 100
        fcf_to_ni       = safe_div(fcf, net_income)

        # ── Valuation (from info snapshot — approximation) ─────────────
        pe_ratio        = info.get("trailingPE")
        pb_ratio        = info.get("priceToBook")
        ev_ebitda       = info.get("enterpriseToEbitda")

        rows.append({
            "ticker":           ticker,
            "quarter":          date,
            "sector":           info.get("sector", ""),
            "industry":         info.get("industry", ""),
            "market_cap":       info.get("marketCap"),
            # Liquidity
            "current_ratio":    float(current_ratio)    if not np.isnan(current_ratio)    else None,
            "quick_ratio":      float(quick_ratio)      if not np.isnan(quick_ratio)      else None,
            "cash_ratio":       float(cash_ratio)       if not np.isnan(cash_ratio)       else None,
            # Leverage
            "debt_to_equity":   float(debt_to_equity)   if not np.isnan(debt_to_equity)   else None,
            "debt_to_assets":   float(debt_to_assets)   if not np.isnan(debt_to_assets)   else None,
            "interest_coverage":float(interest_cover)   if not np.isnan(interest_cover)   else None,
            # Profitability
            "gross_margin":     float(gross_margin)     if not np.isnan(gross_margin)     else None,
            "operating_margin": float(operating_margin) if not np.isnan(operating_margin) else None,
            "net_margin":       float(net_margin)       if not np.isnan(net_margin)       else None,
            "roe":              float(roe)              if not np.isnan(roe)              else None,
            "roa":              float(roa)              if not np.isnan(roa)              else None,
            # Cash flow
            "fcf_margin":       float(fcf_margin)       if not np.isnan(fcf_margin)       else None,
            "fcf_to_net_income":float(fcf_to_ni)        if not np.isnan(fcf_to_ni)        else None,
            # Valuation
            "pe_ratio":         pe_ratio,
            "pb_ratio":         pb_ratio,
            "ev_ebitda":        ev_ebitda,
            # Raw values useful for downstream
            "revenue":          float(revenue)    if not np.isnan(revenue)    else None,
            "net_income":       float(net_income) if not np.isnan(net_income) else None,
            "total_assets":     float(total_assets) if not np.isnan(total_assets) else None,
            "total_debt":       float(total_debt)   if not np.isnan(total_debt)   else None,
        })

    df = pd.DataFrame(rows).set_index(["ticker", "quarter"]).sort_index()

    # ── YoY growth rates ───────────────────────────────────────────────
    rev_series = df["revenue"].reset_index(level=0, drop=True)
    ni_series  = df["net_income"].reset_index(level=0, drop=True)

    df["revenue_growth_yoy"]  = rev_series.pct_change(4) * 100  # 4 quarters back
    df["earnings_growth_yoy"] = ni_series.pct_change(4) * 100

    logger.info(f"  {ticker}: {len(df)} quarters computed")
    return df


# ── Pipeline ──────────────────────────────────────────────────────────────

def build_ratio_dataset(tickers: list[str]) -> pd.DataFrame:
    """
    Compute ratios for all tickers and concatenate into one master DataFrame.
    Saves to data/processed/ratios.parquet
    """
    DATA_PROC.mkdir(parents=True, exist_ok=True)
    all_dfs = []

    for ticker in tickers:
        logger.info(f"Computing ratios for {ticker}...")
        data = load_ticker_data(ticker)
        df   = compute_ratios(ticker, data)
        if df is not None:
            all_dfs.append(df)

    if not all_dfs:
        logger.error("No ratio data computed — check raw data directory.")
        return pd.DataFrame()

    combined = pd.concat(all_dfs)
    out_path = DATA_PROC / "ratios.parquet"
    combined.to_parquet(out_path)
    logger.info(
        f"\nRatio dataset built: {len(combined)} rows, "
        f"{combined.index.get_level_values('ticker').nunique()} tickers → {out_path}"
    )
    return combined


if __name__ == "__main__":
    from config.asx_tickers import ALL_TICKERS
    df = build_ratio_dataset(ALL_TICKERS)
    print(df.describe())
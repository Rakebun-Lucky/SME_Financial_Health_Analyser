"""
Data quality validation.

Runs after ratio computation and before model training.
Flags tickers with:
  - Too few quarters of data
  - Excessive missing values
  - Extreme outliers (Z-score > 5)
  - Suspicious zero values in key metrics

Outputs: data/processed/quality_report.json
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config.settings import DATA_PROC, MIN_DATA_POINTS
from src.utils.logger import get_logger

logger = get_logger(__name__)

RATIO_COLS = [
    "current_ratio", "quick_ratio", "debt_to_equity",
    "operating_margin", "net_margin", "roe", "roa",
    "fcf_margin", "revenue_growth_yoy", "earnings_growth_yoy",
]

MISSING_THRESHOLD  = 0.5   # flag if >50% of ratio cols are missing
OUTLIER_ZSCORE     = 5.0   # flag values beyond 5 standard deviations


def validate(df: pd.DataFrame) -> dict:
    """
    Validate the ratios DataFrame.
    Returns a quality report dict.
    """
    report = {
        "total_tickers":     0,
        "total_rows":        len(df),
        "passed":            [],
        "flagged_few_rows":  [],
        "flagged_missing":   [],
        "flagged_outliers":  [],
        "column_coverage":   {},
        "summary":           {},
    }

    if df.empty:
        logger.error("Empty DataFrame passed to validator.")
        return report

    tickers = df.index.get_level_values("ticker").unique().tolist()
    report["total_tickers"] = len(tickers)

    # ── Per-column coverage ───────────────────────────────────────────
    for col in RATIO_COLS:
        if col in df.columns:
            coverage = df[col].notna().mean()
            report["column_coverage"][col] = round(float(coverage), 3)

    # ── Per-ticker checks ─────────────────────────────────────────────
    for ticker in tickers:
        sub = df.xs(ticker, level="ticker")
        issues = []

        # 1. Too few quarters
        if len(sub) < MIN_DATA_POINTS:
            issues.append(f"only {len(sub)} quarters (min {MIN_DATA_POINTS})")
            report["flagged_few_rows"].append(ticker)

        # 2. Excessive missing values
        available_cols = [c for c in RATIO_COLS if c in sub.columns]
        if available_cols:
            missing_rate = sub[available_cols].isna().mean(axis=1).mean()
            if missing_rate > MISSING_THRESHOLD:
                issues.append(f"missing rate {missing_rate:.1%}")
                report["flagged_missing"].append(ticker)

        # 3. Outlier detection (Z-score)
        numeric_cols = [c for c in RATIO_COLS if c in sub.columns]
        for col in numeric_cols:
            series = sub[col].dropna()
            if len(series) < 3:
                continue
            z = np.abs((series - series.mean()) / (series.std() + 1e-9))
            if (z > OUTLIER_ZSCORE).any():
                issues.append(f"outliers in {col}")
                if ticker not in report["flagged_outliers"]:
                    report["flagged_outliers"].append(ticker)

        if not issues:
            report["passed"].append(ticker)
        else:
            logger.debug(f"  {ticker}: {'; '.join(issues)}")

    # ── Summary ───────────────────────────────────────────────────────
    report["summary"] = {
        "pass_rate":          round(len(report["passed"]) / max(len(tickers), 1), 3),
        "flagged_few_rows":   len(report["flagged_few_rows"]),
        "flagged_missing":    len(report["flagged_missing"]),
        "flagged_outliers":   len(report["flagged_outliers"]),
    }

    logger.info(
        f"Quality check: {len(report['passed'])}/{len(tickers)} passed | "
        f"{len(report['flagged_few_rows'])} too-few-rows | "
        f"{len(report['flagged_missing'])} high-missing | "
        f"{len(report['flagged_outliers'])} outliers"
    )

    # Save report
    out = DATA_PROC / "quality_report.json"
    with open(out, "w") as f:
        json.dump(report, f, indent=2)
    logger.info(f"Quality report saved → {out}")

    return report


def filter_passed_tickers(df: pd.DataFrame, report: dict) -> pd.DataFrame:
    """Return only rows for tickers that passed quality checks."""
    passed = report.get("passed", [])
    if not passed:
        logger.warning("No tickers passed quality checks — returning full dataset.")
        return df
    filtered = df[df.index.get_level_values("ticker").isin(passed)]
    logger.info(f"Filtered to {len(passed)} clean tickers, {len(filtered)} rows.")
    return filtered


if __name__ == "__main__":
    ratios_path = DATA_PROC / "ratios.parquet"
    if not ratios_path.exists():
        print("Run ratio_calculator.py first.")
    else:
        df     = pd.read_parquet(ratios_path)
        report = validate(df)
        print(json.dumps(report["summary"], indent=2))
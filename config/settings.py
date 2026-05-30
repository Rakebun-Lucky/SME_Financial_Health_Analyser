from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA_RAW  = ROOT / "data" / "raw"
DATA_PROC = ROOT / "data" / "processed"

LOOKBACK_YEARS    = 5
REQUEST_DELAY_SEC = 1.0
MAX_RETRIES       = 3
MIN_DATA_POINTS   = 4   # minimum quarters required per ticker

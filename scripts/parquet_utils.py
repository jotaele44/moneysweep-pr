"""
Parquet read/write helpers with graceful CSV fallback when pyarrow is absent.

If pyarrow is installed: writes/reads .parquet files.
If pyarrow is missing:   silently falls back to .csv (same path, .csv extension).

Usage:
    from scripts.parquet_utils import pq_write, pq_read

    pq_write(df, path)        # path is a Path ending in .parquet
    df = pq_read(path)        # returns DataFrame (may be empty on failure)
"""

from pathlib import Path
import pandas as pd

try:
    import pyarrow  # noqa: F401
    _PARQUET_OK = True
except ImportError:
    _PARQUET_OK = False


def pq_write(df: pd.DataFrame, path: Path, **kwargs) -> Path:
    """
    Write DataFrame to parquet, falling back to CSV if pyarrow is unavailable.
    Returns the path actually written.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if _PARQUET_OK:
        try:
            df.to_parquet(path, index=False, engine="pyarrow", **kwargs)
            return path
        except Exception:
            pass
    csv_path = path.with_suffix(".csv")
    df.to_csv(csv_path, index=False, encoding="utf-8")
    return csv_path


def pq_read(path: Path, columns=None) -> pd.DataFrame:
    """
    Read a parquet file, falling back to the .csv equivalent if needed.
    Returns an empty DataFrame (not an error) when neither file exists.
    """
    path = Path(path)
    if _PARQUET_OK and path.exists():
        try:
            return pd.read_parquet(path, engine="pyarrow", columns=columns)
        except Exception:
            pass
    # CSV fallback
    csv_path = path.with_suffix(".csv")
    if csv_path.exists():
        try:
            return pd.read_csv(csv_path, dtype=str, low_memory=False,
                               usecols=columns if columns else None)
        except Exception:
            pass
    return pd.DataFrame()

"""Local market-data access with resilient CPI download and offline fallback."""
from __future__ import annotations

from io import StringIO
from pathlib import Path
import os
import re
import tempfile
from typing import Tuple

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

FRED_CPI_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCNS"
BLS_CPI_URL = "https://download.bls.gov/pub/time.series/cu/cu.data.1.AllItems"
FRED_SERIES_NAME = "CPIAUCNS"
ROOT = Path(__file__).resolve().parents[1]
CACHE_CPI_PATH = ROOT / "data" / "cache" / "cpiaucns.csv"
BUNDLED_CPI_PATH = ROOT / "data" / "reference" / "cpiaucns.csv"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 LocalResearchApp/1.1"


def normalize_ticker(raw_ticker: str) -> str:
    """Normalize a user-entered Yahoo Finance ticker."""
    ticker = (raw_ticker or "").strip().upper().replace(" ", "")
    if not ticker:
        raise ValueError("请输入股票、ETF 或指数代码，例如 VOO、AAPL、0700.HK 或 ^NDX。")
    if re.fullmatch(r"\d{1,4}", ticker):
        return f"{ticker.zfill(4)}.HK"
    return ticker


def _flatten_columns(frame: pd.DataFrame) -> pd.DataFrame:
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    return frame


@st.cache_data(ttl=60 * 60, show_spinner=False)
def download_market_history(ticker: str) -> pd.DataFrame:
    """Download the longest daily OHLCV and corporate-action history Yahoo returns."""
    frame = yf.Ticker(ticker).history(period="max", interval="1d", auto_adjust=False, actions=True, raise_errors=False)
    frame = _flatten_columns(frame.copy())
    if frame.empty:
        raise ValueError(f"Yahoo Finance 没有返回 {ticker} 的日线数据。请检查代码格式；港股示例为 0700.HK。")
    frame.index = pd.to_datetime(frame.index)
    if getattr(frame.index, "tz", None) is not None:
        frame.index = frame.index.tz_localize(None)
    frame.index = frame.index.normalize()
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    required = {"High", "Low", "Close"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Yahoo Finance 返回的数据缺少必要字段：{', '.join(sorted(missing))}。")
    for column in ["Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"]:
        if column not in frame.columns:
            frame[column] = 0.0
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["High", "Low", "Close"])
    if len(frame) < 3:
        raise ValueError(f"{ticker} 的有效日线数据不足 3 个交易日，无法进行分析。")
    return frame


def _parse_cpi_csv(content: bytes | str) -> pd.Series:
    text = content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content
    cpi = pd.read_csv(StringIO(text))
    if len(cpi.columns) < 2:
        raise ValueError("CPI 文件没有日期和值两列。")
    cpi = cpi.iloc[:, :2].copy()
    cpi.columns = ["date", "cpi"]
    cpi["date"] = pd.to_datetime(cpi["date"], errors="coerce")
    cpi["cpi"] = pd.to_numeric(cpi["cpi"], errors="coerce")
    cpi = cpi.dropna().sort_values("date")
    if len(cpi) < 24:
        raise ValueError("CPI 有效月度观测不足 24 条。")
    cpi.index = cpi["date"].dt.to_period("M")
    return cpi["cpi"].rename(FRED_SERIES_NAME)


def _write_cpi_cache(content: bytes) -> None:
    CACHE_CPI_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(prefix="cpiaucns_", suffix=".csv", dir=str(CACHE_CPI_PATH.parent))
    try:
        with os.fdopen(handle, "wb") as fh:
            fh.write(content)
        os.replace(tmp_name, CACHE_CPI_PATH)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _load_cpi_file(path: Path) -> pd.Series:
    return _parse_cpi_csv(path.read_bytes())


def _download_fred_cpi() -> bytes:
    """Use retry plus separate connect/read timeouts; the old 30-second read was brittle."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/csv,text/plain,*/*"})
    last_error: Exception | None = None
    for _ in range(3):
        try:
            response = session.get(FRED_CPI_URL, timeout=(12, 120))
            response.raise_for_status()
            _parse_cpi_csv(response.content)
            return response.content
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"FRED 连续 3 次请求失败：{last_error}")


def _download_bls_cpi() -> bytes:
    """BLS fallback, normalized into the same date/cpi two-column CSV."""
    response = requests.get(BLS_CPI_URL, headers={"User-Agent": USER_AGENT}, timeout=(12, 120))
    response.raise_for_status()
    raw = pd.read_csv(StringIO(response.text), sep="\t")
    raw.columns = [str(c).strip() for c in raw.columns]
    raw["series_id"] = raw["series_id"].astype(str).str.strip()
    raw = raw[(raw["series_id"] == "CUSR0000SA0") & raw["period"].astype(str).str.match(r"M\d{2}")].copy()
    raw["month"] = raw["period"].astype(str).str[1:].astype(int)
    raw["date"] = pd.to_datetime(dict(year=pd.to_numeric(raw["year"]), month=raw["month"], day=1), errors="coerce")
    raw["cpi"] = pd.to_numeric(raw["value"], errors="coerce")
    clean = raw[["date", "cpi"]].dropna().sort_values("date")
    if len(clean) < 24:
        raise ValueError("BLS CPI 备用通道未返回足够月度数据。")
    return clean.to_csv(index=False).encode("utf-8")


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def load_us_cpi() -> tuple[pd.Series, str]:
    """Load CPI via FRED → BLS → refreshed local cache → bundled offline file.

    Online failures never remove real-return functionality when a cache exists.
    """
    failures: list[str] = []
    for name, loader in [("FRED 在线数据", _download_fred_cpi), ("BLS 在线备用数据", _download_bls_cpi)]:
        try:
            content = loader()
            series = _parse_cpi_csv(content)
            _write_cpi_cache(content)
            return series, name
        except Exception as exc:
            failures.append(f"{name}：{exc}")
    for name, path in [("本地缓存 CPI", CACHE_CPI_PATH), ("随程序附带的离线 CPI", BUNDLED_CPI_PATH)]:
        try:
            if path.exists():
                return _load_cpi_file(path), f"{name}（在线下载失败后回退）"
        except Exception as exc:
            failures.append(f"{name}：{exc}")
    raise ValueError("无法加载美国 CPI。" + "；".join(failures) + f"。可将 CPIAUCNS CSV 放入：{CACHE_CPI_PATH}")


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def get_ticker_label(ticker: str) -> str:
    """Return a best-effort display name without making the page depend on it."""
    try:
        info = yf.Ticker(ticker).get_fast_info()
        name = getattr(info, "longName", None) or getattr(info, "shortName", None)
        return str(name) if name else ticker
    except Exception:
        return ticker


def data_summary(frame: pd.DataFrame) -> Tuple[pd.Timestamp, pd.Timestamp, int, int]:
    """Return start date, end date, trading-day count and positive-dividend count."""
    dividends = frame.get("Dividends", pd.Series(0.0, index=frame.index)).fillna(0.0)
    return frame.index.min(), frame.index.max(), len(frame), int((dividends > 0).sum())

"""Market-data access functions for the Streamlit application."""
from __future__ import annotations

from io import StringIO
import re
from typing import Tuple

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

FRED_CPI_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCNS"
FRED_SERIES_NAME = "CPIAUCNS"


def normalize_ticker(raw_ticker: str) -> str:
    """Normalize a user-entered Yahoo Finance ticker.

    A four-digit Hong Kong equity code entered without a suffix is converted to
    the Yahoo Finance convention, for example ``700`` becomes ``0700.HK``.
    """
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
    """Download the longest daily OHLCV and corporate-action history Yahoo returns.

    ``period='max'`` is deliberately used instead of a fixed start date. Yahoo
    Finance determines the earliest available observation for each ticker.
    """
    frame = yf.Ticker(ticker).history(
        period="max",
        interval="1d",
        auto_adjust=False,
        actions=True,
        raise_errors=False,
    )
    frame = _flatten_columns(frame.copy())
    if frame.empty:
        raise ValueError(
            f"Yahoo Finance 没有返回 {ticker} 的日线数据。请检查代码格式；港股示例为 0700.HK。"
        )

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


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def load_us_cpi() -> pd.Series:
    """Load the monthly, non-seasonally-adjusted U.S. CPI-U series from FRED."""
    try:
        response = requests.get(FRED_CPI_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        cpi = pd.read_csv(StringIO(response.text))
    except Exception as exc:
        raise ValueError(f"无法从 FRED 获取美国 CPI 数据：{exc}") from exc

    if len(cpi.columns) < 2:
        raise ValueError("FRED CPI 数据格式异常。")
    cpi = cpi.iloc[:, :2].copy()
    cpi.columns = ["date", "cpi"]
    cpi["date"] = pd.to_datetime(cpi["date"], errors="coerce")
    cpi["cpi"] = pd.to_numeric(cpi["cpi"], errors="coerce")
    cpi = cpi.dropna().sort_values("date")
    cpi.index = cpi["date"].dt.to_period("M")
    return cpi["cpi"].rename(FRED_SERIES_NAME)


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

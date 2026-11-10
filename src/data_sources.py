"""Local market-data access with offline CPI (no online CPI download)."""
from __future__ import annotations

from pathlib import Path
from io import StringIO
import re
from typing import Tuple

import pandas as pd
import streamlit as st
import yfinance as yf

FRED_SERIES_NAME = "CPIAUCNS"
ROOT = Path(__file__).resolve().parents[1]
CACHE_CPI_PATH = ROOT / "data" / "cache" / "cpiaucns.csv"
BUNDLED_CPI_PATH = ROOT / "data" / "reference" / "cpiaucns.csv"


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


def _load_cpi_file(path: Path) -> pd.Series:
    return _parse_cpi_csv(path.read_bytes())


def _extend_to_current_month(series: pd.Series) -> pd.Series:
    """文件里没有最新月份时，沿用文件中最近一个月的 CPI 值。"""
    current = pd.Period(pd.Timestamp.today(), freq="M")
    last = series.index.max()
    if last >= current:
        return series
    full_index = pd.period_range(series.index.min(), current, freq="M")
    return series.reindex(full_index).ffill().rename(FRED_SERIES_NAME)


@st.cache_data(ttl=60 * 60, show_spinner=False)
def load_us_cpi() -> tuple[pd.Series, str]:
    """只读本地 CPI 文件：优先用月份最新的一份，缺失月份沿用最近值。不联网。"""
    failures: list[str] = []
    best_series, best_name = None, ""
    for name, path in [("本地缓存 CPI", CACHE_CPI_PATH), ("随程序附带的离线 CPI", BUNDLED_CPI_PATH)]:
        try:
            if path.exists():
                s = _load_cpi_file(path)
                if best_series is None or s.index.max() > best_series.index.max():
                    best_series, best_name = s, name
        except Exception as exc:
            failures.append(f"{name}：{exc}")

    if best_series is None:
        raise ValueError(
            "无法加载美国 CPI 本地文件。" + "；".join(failures)
            + f"。请将 CPIAUCNS CSV 放入：{BUNDLED_CPI_PATH}"
        )

    last = best_series.index.max()
    return _extend_to_current_month(best_series), f"{best_name}（最新到 {last}，之后月份沿用该值）"


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

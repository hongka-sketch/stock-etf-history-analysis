"""Intraday drawdown and recovery-time calculations."""
from __future__ import annotations

import numpy as np
import pandas as pd

SCOPE_LABELS = {"daily": "当日", "monthly": "当月", "yearly": "当年"}


def _format_date(index: pd.DatetimeIndex, position: int) -> str:
    return index[position].strftime("%Y-%m-%d")


def _recovery(high: np.ndarray, dates: pd.DatetimeIndex, trough_position: int, level: float) -> dict:
    """Find the first subsequent session with an intraday high at or above level."""
    following = high[trough_position + 1 :]
    matched = np.where(following >= level)[0]
    if len(matched):
        recovery_position = trough_position + 1 + int(matched[0])
        return {
            "已恢复": True,
            "恢复日": _format_date(dates, recovery_position),
            "恢复天数": int((dates[recovery_position] - dates[trough_position]).days),
            "恢复交易日": int(recovery_position - trough_position),
        }
    return {
        "已恢复": False,
        "恢复日": None,
        "恢复天数": int((dates[-1] - dates[trough_position]).days),
        "恢复交易日": int(len(dates) - 1 - trough_position),
    }


def _pack(
    high: np.ndarray,
    dates: pd.DatetimeIndex,
    drawdown: float,
    peak_position: int,
    trough_position: int,
    level: float,
) -> dict:
    recovery = _recovery(high, dates, trough_position, level)
    return {
        "最大回撤%": round(float(drawdown) * 100.0, 2),
        "高点日": _format_date(dates, peak_position),
        "低点日": _format_date(dates, trough_position),
        "恢复水平": round(float(level), 2),
        **recovery,
    }


def _span_drawdown(high: np.ndarray, low: np.ndarray, start: int, end: int) -> tuple[float, int, int, float] | None:
    """Find maximum high-to-later-low drawdown in positional range [start, end)."""
    if end - start < 2:
        return None
    highs = high[start:end]
    lows = low[start:end]
    rolling_peak = np.maximum.accumulate(highs)
    drawdowns = lows[1:] / rolling_peak[:-1] - 1.0
    trough_relative = int(np.argmin(drawdowns)) + 1
    peak_value = rolling_peak[trough_relative - 1]
    peak_relative = int(np.where(highs[:trough_relative] == peak_value)[0][0])
    return float(drawdowns[trough_relative - 1]), start + peak_relative, start + trough_relative, float(peak_value)


def calculate_drawdowns(history: pd.DataFrame) -> pd.DataFrame:
    """Calculate a daily, monthly and yearly maximum drawdown for every full year."""
    data = history[["High", "Low", "Close"]].dropna().sort_index().copy()
    dates = pd.DatetimeIndex(data.index)
    high = data["High"].to_numpy(dtype=float)
    low = data["Low"].to_numpy(dtype=float)
    close = data["Close"].to_numpy(dtype=float)
    years = dates.year.to_numpy()
    months = dates.month.to_numpy()
    previous_close = np.roll(close, 1)
    previous_close[0] = np.nan

    records: list[dict] = []
    for year in sorted(set(years)):
        positions = np.where(years == year)[0]
        if not len(positions):
            continue
        first, last = int(positions[0]), int(positions[-1])
        if dates[first].month != 1 or dates[last].month != 12:
            continue

        current: dict[str, object] = {"年份": int(year)}
        usable = positions[~np.isnan(previous_close[positions])]
        if len(usable):
            daily_dd = np.minimum(low[usable] / previous_close[usable] - 1.0, 0.0)
            trough = int(usable[int(np.argmin(daily_dd))])
            current["daily"] = _pack(high, dates, float(daily_dd.min()), trough - 1, trough, float(previous_close[trough]))
        else:
            current["daily"] = None

        monthly_best: tuple[tuple[float, int, int, float], int] | None = None
        for month in range(1, 13):
            monthly_positions = np.where((years == year) & (months == month))[0]
            if len(monthly_positions):
                result = _span_drawdown(high, low, int(monthly_positions[0]), int(monthly_positions[-1]) + 1)
                if result and (monthly_best is None or result[0] < monthly_best[0][0]):
                    monthly_best = (result, month)
        if monthly_best:
            (dd, peak, trough, level), month = monthly_best
            current["monthly"] = {**_pack(high, dates, min(dd, 0.0), peak, trough, level), "最深回撤月份": int(month)}
        else:
            current["monthly"] = None

        annual_result = _span_drawdown(high, low, first, last + 1)
        if annual_result:
            dd, peak, trough, level = annual_result
            current["yearly"] = _pack(high, dates, min(dd, 0.0), peak, trough, level)
        else:
            current["yearly"] = None
        records.append(current)
    return pd.DataFrame.from_records(records)


def scope_table(drawdowns: pd.DataFrame, scope: str) -> pd.DataFrame:
    """Flatten one scope into a user-facing table."""
    if drawdowns.empty:
        return pd.DataFrame()
    rows: list[dict] = []
    for _, record in drawdowns.iterrows():
        detail = record.get(scope)
        if isinstance(detail, dict):
            rows.append({"年份": int(record["年份"]), **detail})
    return pd.DataFrame(rows)


def recovery_summary(scope_data: pd.DataFrame) -> dict:
    """Produce key recovery statistics for a flattened scope table."""
    if scope_data.empty:
        return {}
    recovered = scope_data[scope_data["已恢复"]].copy()
    pending = scope_data[~scope_data["已恢复"]].copy()
    days = recovered["恢复天数"] if not recovered.empty else pd.Series(dtype=float)
    return {
        "样本年数": int(len(scope_data)),
        "已恢复年数": int(len(recovered)),
        "尚未恢复年数": int(len(pending)),
        "平均恢复天数": float(days.mean()) if len(days) else np.nan,
        "中位恢复天数": float(days.median()) if len(days) else np.nan,
        "最短恢复天数": float(days.min()) if len(days) else np.nan,
        "最长恢复天数": float(days.max()) if len(days) else np.nan,
    }

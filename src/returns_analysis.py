"""Annual entry-point and holding-return calculations."""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

BUY_LABELS = {
    "high": "年度最高点",
    "average": "最接近年均价",
    "low": "年度最低点",
}


def complete_calendar_years(index: pd.DatetimeIndex) -> list[int]:
    """Return years with observations in both January and December."""
    years: list[int] = []
    for year, dates in pd.Series(index=index, data=index).groupby(index.year):
        if dates.min().month == 1 and dates.max().month == 12:
            years.append(int(year))
    return years


def build_return_indices(history: pd.DataFrame, withholding_tax: float) -> pd.DataFrame:
    """Build price, pretax-total-return and after-tax-total-return indices.

    The total-return approximation reinvests each cash dividend on its recorded
    date. It deliberately uses the selected ticker's own dividend history.
    """
    close = history["Close"].astype(float)
    price_return = close.pct_change().fillna(0.0)
    dividends = history.get("Dividends", pd.Series(0.0, index=history.index)).fillna(0.0).astype(float)
    prior_close = close.shift(1)
    dividend_yield = (dividends / prior_close).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    index = pd.DataFrame(index=history.index)
    index["价格"] = (1.0 + price_return).cumprod()
    index["含息（税前）"] = (1.0 + price_return + dividend_yield).cumprod()
    index["含息（税后）"] = (1.0 + price_return + (1.0 - withholding_tax) * dividend_yield).cumprod()
    return index


def _entry_points(year_data: pd.DataFrame) -> dict[str, tuple[pd.Timestamp, float]]:
    high_date = year_data["High"].idxmax()
    low_date = year_data["Low"].idxmin()
    annual_mean = float(year_data["Close"].mean())
    distances = (year_data["Close"] - annual_mean).abs()
    candidate_dates = distances[distances == distances.min()].index.sort_values()
    average_date = candidate_dates[len(candidate_dates) // 2]
    return {
        "high": (high_date, float(year_data.loc[high_date, "High"])),
        "average": (average_date, float(year_data.loc[average_date, "Close"])),
        "low": (low_date, float(year_data.loc[low_date, "Low"])),
    }


def _end_date(index: pd.DatetimeIndex, target: pd.Timestamp) -> pd.Timestamp | None:
    pos = index.searchsorted(target, side="left")
    if pos >= len(index):
        return None
    return index[pos]


def calculate_holding_returns(
    history: pd.DataFrame,
    cpi: pd.Series | None,
    windows: Iterable[int],
    withholding_tax: float,
) -> pd.DataFrame:
    """Calculate annualized returns for annual high/average/low entry points."""
    windows = sorted({int(value) for value in windows if int(value) > 0})
    indices = build_return_indices(history, withholding_tax)
    complete_years = complete_calendar_years(history.index)
    if not complete_years:
        return pd.DataFrame()

    latest_date = history.index.max()
    close = history["Close"].astype(float)
    records: list[dict] = []

    for year in complete_years:
        year_data = history.loc[history.index.year == year]
        entries = _entry_points(year_data)
        for entry_id, (entry_date, entry_price) in entries.items():
            for years in windows:
                target = entry_date + pd.DateOffset(years=years)
                exit_date = _end_date(history.index, target)
                if exit_date is None or exit_date > latest_date:
                    continue

                inflation_factor = np.nan
                if cpi is not None:
                    buy_month = entry_date.to_period("M")
                    sell_month = exit_date.to_period("M")
                    if buy_month in cpi.index and sell_month in cpi.index:
                        inflation_factor = float(cpi.loc[sell_month] / cpi.loc[buy_month])

                for basis in indices.columns:
                    # Buy at the specified high/low/close. The index itself is anchored
                    # to closing prices, so scale it by that date's closing-to-entry ratio.
                    gross_factor = float(indices.loc[exit_date, basis] / indices.loc[entry_date, basis])
                    gross_factor *= float(close.loc[entry_date] / entry_price)
                    nominal_total = (gross_factor - 1.0) * 100.0
                    nominal_annual = (gross_factor ** (1.0 / years) - 1.0) * 100.0
                    records.append(
                        {
                            "买入年份": year,
                            "买点ID": entry_id,
                            "买点": BUY_LABELS[entry_id],
                            "买入日": entry_date,
                            "买入价": entry_price,
                            "卖出日": exit_date,
                            "持有期（年）": years,
                            "回报口径": basis,
                            "名义总回报%": nominal_total,
                            "名义年化回报%": nominal_annual,
                            "通胀因子": inflation_factor,
                            "实际总回报%": ((gross_factor / inflation_factor) - 1.0) * 100.0 if pd.notna(inflation_factor) else np.nan,
                            "实际年化回报%": ((gross_factor / inflation_factor) ** (1.0 / years) - 1.0) * 100.0 if pd.notna(inflation_factor) else np.nan,
                        }
                    )
    return pd.DataFrame.from_records(records)


def summarise_returns(data: pd.DataFrame, value_column: str) -> pd.DataFrame:
    """Summarize annualized-return samples by entry point, basis and horizon."""
    if data.empty or value_column not in data:
        return pd.DataFrame()
    clean = data.dropna(subset=[value_column]).copy()
    if clean.empty:
        return pd.DataFrame()

    grouped = clean.groupby(["买点", "回报口径", "持有期（年）"], sort=False)[value_column]
    summary = grouped.agg(
        样本数="count",
        平均值="mean",
        中位数="median",
        最低值="min",
        最高值="max",
        亏损占比=lambda values: (values < 0).mean() * 100,
    ).reset_index()
    return summary.rename(columns={
        "平均值": "平均年化%",
        "中位数": "中位年化%",
        "最低值": "最低年化%",
        "最高值": "最高年化%",
        "亏损占比": "亏损占比%",
    })


def entry_price_comparison(data: pd.DataFrame) -> pd.DataFrame:
    """Return a pivot table of entry prices for each annual observation."""
    if data.empty:
        return pd.DataFrame()
    base = data[["买入年份", "买点", "买入日", "买入价"]].drop_duplicates()
    return base.pivot(index="买入年份", columns="买点", values="买入价").reset_index()

"""Streamlit entry point for the market return and drawdown explorer."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.data_sources import data_summary, download_market_history, load_us_cpi, normalize_ticker
from src.drawdown_analysis import calculate_drawdowns
from src.ui_components import render_drawdown_tab, render_returns_tab

st.set_page_config(page_title="股票与 ETF 历史分析", page_icon="📈", layout="wide")

st.title("股票与 ETF 历史分析")
st.write("输入一个 Yahoo Finance 代码，两个分析标签页会使用同一标的与其最长可用日线历史数据。")

if "active_ticker" not in st.session_state:
    st.session_state.active_ticker = "VOO"

with st.form("ticker_form", clear_on_submit=False):
    input_col, button_col = st.columns([4, 1])
    with input_col:
        raw_ticker = st.text_input(
            "股票、ETF 或指数代码",
            value=st.session_state.active_ticker,
            help="示例：VOO、AAPL、QQQ、0700.HK、^NDX。纯数字 700 会按港股自动转换为 0700.HK。",
        )
    with button_col:
        st.write("")
        submitted = st.form_submit_button("更新分析", use_container_width=True)

if submitted:
    try:
        st.session_state.active_ticker = normalize_ticker(raw_ticker)
    except ValueError as error:
        st.error(str(error))
        st.stop()

ticker = st.session_state.active_ticker
try:
    with st.spinner(f"正在从 Yahoo Finance 请求 {ticker} 的最长可用日线历史数据……"):
        history = download_market_history(ticker)
except ValueError as error:
    st.error(str(error))
    st.info("请尝试 Yahoo Finance 支持的代码格式，例如 VOO、AAPL、0700.HK 或 ^NDX。")
    st.stop()

start, end, trading_days, dividend_events = data_summary(history)
is_hk = ticker.endswith(".HK")

info_left, info_middle, info_right, info_last = st.columns(4)
info_left.metric("当前标的", ticker)
info_middle.metric("Yahoo 可用历史", f"{start:%Y-%m-%d} 至 {end:%Y-%m-%d}")
info_right.metric("交易日", f"{trading_days:,}")
info_last.metric("现金分红记录", f"{dividend_events:,}")

with st.expander("数据来源、计算范围与重要限制", expanded=False):
    st.markdown(
        """
**市场数据。** 日线 Open、High、Low、Close、成交量、现金分红和拆股信息均通过 `yfinance` 请求 Yahoo Finance。应用固定使用 `period='max'`，因此对每一个代码请求 Yahoo Finance **能够返回的最长日线历史**；实际开始日期取决于该标的的上市时间和 Yahoo 的覆盖范围。

**通胀。** 只有在第一个标签页选择“美国 CPI 调整后”时，应用才使用 FRED 的 `CPIAUCNS` 月度 CPI-U（原始来源为美国劳工统计局）。这反映美元的美国购买力变化；若分析 `0700.HK` 等港股，它并不代表香港本地通胀调整。

**分红。** 含息回报使用输入标的自身在 Yahoo Finance 中返回的现金分红，不再将 QQQ 分红套用于其他标的。Yahoo 未提供分红记录的指数或标的，含息和价格口径会相同。

**用途。** 历史结果仅供研究与教育用途，不构成投资建议。年度最高点、均价点和最低点均为事后定义，无法在买入当日确认。
        """
    )

try:
    with st.spinner("正在加载美国 CPI（仅用于实际回报计算）……"):
        cpi = load_us_cpi()
except ValueError as error:
    cpi = None
    st.warning(str(error))

with st.spinner("正在计算最大回撤与恢复时间……"):
    drawdowns = calculate_drawdowns(history)

returns_tab, drawdown_tab = st.tabs(["年度买点与持有回报", "最大回撤与恢复时间"])
with returns_tab:
    render_returns_tab(history=history, cpi=cpi, ticker=ticker, is_hk=is_hk)
with drawdown_tab:
    render_drawdown_tab(history=history, ticker=ticker, drawdowns=drawdowns)

st.divider()
st.caption("数据更新时间取决于 Yahoo Finance 与 FRED 的可用性。下载与计算结果在应用会话中缓存，以减少重复请求。")

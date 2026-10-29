"""Streamlit rendering functions for both analysis tabs."""
from __future__ import annotations

from io import BytesIO

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.drawdown_analysis import SCOPE_LABELS, recovery_summary, scope_table
from src.returns_analysis import BUY_LABELS, calculate_holding_returns, entry_price_comparison, summarise_returns


def _csv_bytes(data: pd.DataFrame) -> bytes:
    return data.to_csv(index=False).encode("utf-8-sig")


def _format_pct(value: float) -> str:
    return "—" if pd.isna(value) else f"{value:.2f}%"


def render_returns_tab(history: pd.DataFrame, cpi: pd.Series | None, ticker: str, is_hk: bool) -> None:
    st.subheader("年度买点与持有回报")
    st.caption("按每个完整日历年的年度最高点、最接近年均收盘价点和年度最低点进行事后对照；并非可实时执行的择时策略。")

    left, middle, right = st.columns([1.2, 1.2, 1])
    with left:
        windows = st.multiselect("持有期（年）", options=[1, 3, 5, 7, 10, 15, 20, 25], default=[3, 5, 7, 10])
    with middle:
        withholding_tax = st.slider("分红预扣税率", min_value=0, max_value=40, value=15, step=1) / 100
    with right:
        return_type = st.radio("回报显示", options=["名义回报", "美国 CPI 调整后"], horizontal=False)

    if not windows:
        st.info("请至少选择一个持有期。")
        return
    if return_type == "美国 CPI 调整后" and cpi is None:
        st.warning("目前无法取得 FRED CPI 数据，因此只能计算名义回报。")
        return
    if is_hk and return_type == "美国 CPI 调整后":
        st.warning("该标的是港股；美国 CPI 调整表示以美国 CPI 衡量购买力变化，并不等于香港本地通胀调整后的回报。")

    with st.spinner("正在计算各年度买点的持有回报……"):
        returns = calculate_holding_returns(history, cpi, windows, withholding_tax)
    if returns.empty:
        st.warning("该标的没有足够的完整年度和持有期数据来计算结果。")
        return

    value_column = "实际年化回报%" if return_type == "美国 CPI 调整后" else "名义年化回报%"
    available = returns.dropna(subset=[value_column]).copy()
    if available.empty:
        st.warning("所选口径没有可用样本。请缩短持有期，或改为名义回报。")
        return

    basis_options = available["回报口径"].drop_duplicates().tolist()
    basis = st.selectbox("分红口径", basis_options, index=min(1, len(basis_options) - 1))
    filtered = available[available["回报口径"] == basis].copy()

    dividend_count = int((history.get("Dividends", pd.Series(0, index=history.index)) > 0).sum())
    if dividend_count == 0:
        st.info("Yahoo Finance 未返回该标的的现金分红记录；“含息”与“价格”口径在此情形下相同。")

    chart = px.line(
        filtered,
        x="买入年份",
        y=value_column,
        color="买点",
        facet_col="持有期（年）",
        facet_col_wrap=2,
        markers=True,
        category_orders={"买点": list(BUY_LABELS.values())},
        labels={value_column: "年化回报（%）", "买入年份": "买入年份", "买点": "买点"},
        title=f"{ticker}：{basis} · {return_type}年化回报",
    )
    chart.add_hline(y=0, line_dash="dot", line_color="gray")
    chart.update_layout(height=max(420, 360 * ((len(windows) + 1) // 2)), legend_title_text="买点")
    st.plotly_chart(chart, use_container_width=True)

    summary = summarise_returns(filtered, value_column)
    st.markdown("#### 汇总统计")
    summary_display = summary.copy()
    for column in ["平均年化%", "中位年化%", "最低年化%", "最高年化%", "亏损占比%"]:
        summary_display[column] = summary_display[column].map(_format_pct)
    st.dataframe(summary_display, use_container_width=True, hide_index=True)

    st.markdown("#### 年化回报分布")
    horizon = st.selectbox("用于分布图的持有期", sorted(filtered["持有期（年）"].unique()), key="returns_distribution_horizon")
    distribution = filtered[filtered["持有期（年）"] == horizon]
    histogram = px.histogram(
        distribution,
        x=value_column,
        color="买点",
        barmode="overlay",
        nbins=18,
        opacity=0.65,
        labels={value_column: "年化回报（%）", "买点": "买点"},
        title=f"{horizon} 年持有期：年化回报分布",
    )
    histogram.add_vline(x=0, line_dash="dot", line_color="gray")
    st.plotly_chart(histogram, use_container_width=True)

    with st.expander("查看年度买入价和原始计算结果"):
        price_comparison = entry_price_comparison(filtered)
        st.dataframe(price_comparison, use_container_width=True, hide_index=True)
        st.dataframe(filtered.sort_values(["买入年份", "持有期（年）", "买点"]), use_container_width=True, hide_index=True)

    st.download_button(
        "下载持有回报明细 CSV",
        data=_csv_bytes(returns.sort_values(["买入年份", "持有期（年）", "买点", "回报口径"])),
        file_name=f"{ticker}_holding_returns.csv",
        mime="text/csv",
    )
    st.caption("“含息”回报按 Yahoo Finance 返回的该标的现金分红进行除息日再投资模拟；税后口径按所选税率从每次现金分红中扣减后再投资。")


def render_drawdown_tab(history: pd.DataFrame, ticker: str, drawdowns: pd.DataFrame) -> None:
    st.subheader("最大回撤与恢复时间")
    st.caption("全程使用盘中 High/Low：当日回撤为当日最低价相对前收；当月和当年回撤为该时间范围内较早高点至随后低点的最大跌幅。")

    scope = st.radio(
        "分析周期",
        options=list(SCOPE_LABELS),
        format_func=lambda value: SCOPE_LABELS[value],
        horizontal=True,
    )
    scoped = scope_table(drawdowns, scope)
    if scoped.empty:
        st.warning("该标的缺少足够的完整年份数据，无法计算所选回撤分析。")
        return

    stats = recovery_summary(scoped)
    metrics = st.columns(5)
    metrics[0].metric("样本年数", f"{stats['样本年数']} 年")
    metrics[1].metric("已恢复", f"{stats['已恢复年数']} 年")
    metrics[2].metric("尚未恢复", f"{stats['尚未恢复年数']} 年")
    metrics[3].metric("恢复天数中位数", "—" if pd.isna(stats["中位恢复天数"]) else f"{stats['中位恢复天数']:.0f} 天")
    metrics[4].metric("最长已恢复", "—" if pd.isna(stats["最长恢复天数"]) else f"{stats['最长恢复天数']:.0f} 天")

    recovery_values = scoped["恢复天数"].copy()
    colors = ["#B22222" if not flag else "#D85A30" for flag in scoped["已恢复"]]
    recovery_chart = go.Figure(go.Bar(
        x=scoped["年份"], y=recovery_values, marker_color=colors,
        customdata=scoped[["最大回撤%", "高点日", "低点日", "恢复日", "已恢复"]].to_numpy(),
        hovertemplate=("年份 %{x}<br>恢复天数 %{y}<br>最大回撤 %{customdata[0]:.2f}%"
                       "<br>高点 %{customdata[1]}<br>低点 %{customdata[2]}<br>恢复日 %{customdata[3]}<extra></extra>"),
    ))
    recovery_chart.update_layout(title=f"{ticker}：{SCOPE_LABELS[scope]}最大回撤的恢复天数", xaxis_title="年份", yaxis_title="恢复天数", height=430)
    recovery_chart.update_yaxes(type="log", tickmode="array")
    st.plotly_chart(recovery_chart, use_container_width=True)

    dd_chart = px.bar(
        scoped, x="年份", y="最大回撤%", color_discrete_sequence=["#1F8A70"],
        hover_data=["高点日", "低点日", "恢复水平", "恢复日", "恢复天数"],
        title=f"{ticker}：{SCOPE_LABELS[scope]}最大回撤",
    )
    dd_chart.update_layout(height=380, yaxis_title="最大回撤（%）")
    st.plotly_chart(dd_chart, use_container_width=True)

    st.markdown("#### 恢复时间分布")
    bins = [-0.5, 7, 30, 91, 182, 365, 730, 1825, 3650, float("inf")]
    labels = ["1周内", "1周–1个月", "1–3个月", "3–6个月", "6–12个月", "1–2年", "2–5年", "5–10年", "10年以上"]
    recovered = scoped[scoped["已恢复"]].copy()
    if not recovered.empty:
        recovered["恢复区间"] = pd.cut(recovered["恢复天数"], bins=bins, labels=labels)
        counts = recovered["恢复区间"].value_counts().reindex(labels, fill_value=0).reset_index()
        counts.columns = ["恢复区间", "年份数"]
        st.plotly_chart(px.bar(counts, x="恢复区间", y="年份数", title="已恢复年份的恢复时间分布"), use_container_width=True)
    else:
        st.info("所选口径没有已恢复的观察值。")

    with st.expander("查看年度明细"):
        display = scoped.copy()
        display["已恢复"] = display["已恢复"].map({True: "是", False: "否"})
        st.dataframe(display, use_container_width=True, hide_index=True)

    st.download_button(
        "下载回撤与恢复明细 CSV",
        data=_csv_bytes(scoped),
        file_name=f"{ticker}_{scope}_drawdown_recovery.csv",
        mime="text/csv",
    )

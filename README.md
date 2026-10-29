# 股票与 ETF 历史分析（Streamlit）

这是一个以 **Yahoo Finance 代码**为输入的 Streamlit 网页。页面顶部只有一个共享输入框；输入一次股票、ETF 或指数代码后，两个标签页都会围绕同一个标的更新。默认标的是 `VOO`。

应用固定使用 `yfinance` 的 `period="max"` 获取 Yahoo Finance 对该代码能够返回的**最长日线历史数据**，而不是限制为预设起始日期。因此，最终可分析时间跨度取决于该标的的上市历史与 Yahoo Finance 数据覆盖范围。

## 功能

| 标签页 | 内容 |
|---|---|
| 年度买点与持有回报 | 对每个完整日历年分别使用年度最高点、最接近年均收盘价点、年度最低点作为事后对照买点；计算 1、3、5、7、10、15、20、25 年持有期的价格／税前含息／税后含息回报、年化回报、分布与汇总统计 |
| 最大回撤与恢复时间 | 基于盘中 High/Low，计算每个完整年度中最深的当日、当月和当年回撤，以及从低点后回到原高点所需的日历天数与交易日 |

## 代码输入

| 市场或标的 | 输入示例 |
|---|---|
| 美国股票 | `AAPL` |
| 美国 ETF | `VOO`、`QQQ` |
| 香港股票 | `0700.HK`、`9988.HK` |
| 港股简写 | `700` 会自动规范为 `0700.HK` |
| 指数 | `^NDX`、`^GSPC` |

## 数据来源与计算口径

日线 Open、High、Low、Close、成交量、现金分红与拆股均经 `yfinance` 从 Yahoo Finance 请求。`yfinance` 是使用 Yahoo 公开接口的开源项目，并非 Yahoo 官方 SDK；请自行确认 Yahoo 的使用条款和适用范围。[1]

实际回报使用 FRED 提供的 `CPIAUCNS` 月度美国 CPI-U 折算。该序列原始来源为美国劳工统计局（BLS），为未季调、基期 1982–1984=100 的美国城市消费者价格指数。[2]

> 对港股（例如 `0700.HK`）选择“美国 CPI 调整后”时，结果代表以美国 CPI 衡量购买力变化，不代表香港本地通胀调整后的回报。港股的本币名义回报与回撤计算不受此限制。

含息回报基于**输入标的本身**的现金分红记录模拟再投资，而不是以某只 ETF 代理其他股票或指数。若 Yahoo Finance 没有返回分红记录，含息与价格口径会相同。税后含息口径按页面选择的预扣税率逐次扣减现金分红后再投资；该计算为研究用模拟，不等同于券商实际结算。

## 本地运行

需要 Python 3.10 或更高版本。建议在虚拟环境中运行：

```bash
git clone https://github.com/你的用户名/stock-etf-history-analysis.git
cd stock-etf-history-analysis
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Windows PowerShell 激活虚拟环境的命令为：

```powershell
.venv\Scripts\Activate.ps1
```

启动后，在浏览器打开终端显示的本地地址（通常为 `http://localhost:8501`）。

## 上传到 GitHub

### 方式一：网页上传（最简单）

1. 登录 GitHub 并点击右上角 **+**，选择 **New repository**。
2. 仓库名称建议填写 `stock-etf-history-analysis`，选择 **Public**；不要勾选自动创建 README、`.gitignore` 或 License，因为本项目已包含这些文件。
3. 点击 **Create repository**。
4. 在新仓库点击 **Add file** → **Upload files**。
5. 把本项目目录内的全部文件和文件夹拖入上传区域，务必包含 `app.py`、`requirements.txt`、`README.md`、`src/` 和 `.streamlit/`。
6. 在页面底部填写提交说明，例如 `Initial Streamlit app`，然后点击 **Commit changes**。

### 方式二：Git 命令行

在项目目录运行以下命令。请将链接替换为您新建仓库实际显示的 HTTPS 地址：

```bash
git init
git add .
git commit -m "Initial Streamlit market analysis app"
git branch -M main
git remote add origin https://github.com/你的用户名/stock-etf-history-analysis.git
git push -u origin main
```

## 部署到 Streamlit Community Cloud

1. 打开 [Streamlit Community Cloud](https://share.streamlit.io/)，使用 GitHub 账号登录并授权访问刚创建的仓库。
2. 点击 **Create app**，选择您的 GitHub 仓库、分支 `main`。
3. 在 **Main file path** 中填写 `app.py`。
4. 确认 Python 版本使用平台默认的稳定版本，然后点击 **Deploy**。
5. 第一次部署会依据 `requirements.txt` 安装依赖，通常需要数分钟。部署完成后会获得一个 `streamlit.app` 公网地址。
6. 日后修改代码后，提交并推送到 `main` 分支；平台会自动重新部署。若未自动更新，可在应用管理页面选择重新启动或重新部署。

本项目不需要 API Key、数据库或 Streamlit Secrets，因此部署时无需配置 Secrets。

## 文件结构

```text
stock-etf-history-analysis/
├── app.py
├── requirements.txt
├── README.md
├── .gitignore
├── .streamlit/
│   └── config.toml
└── src/
    ├── __init__.py
    ├── data_sources.py
    ├── returns_analysis.py
    ├── drawdown_analysis.py
    └── ui_components.py
```

## 重要限制

| 项目 | 限制 |
|---|---|
| 历史长度 | 请求 `period="max"`，但不能超出 Yahoo Finance 实际提供的最早记录；新上市标的没有足够历史时，长持有期的样本会为空 |
| 数据可用性 | Yahoo Finance 可能有延迟、临时错误、代码更名或个别字段缺失；应用会显示无法计算的提示而不进行补造数据 |
| 回撤 | 使用未复权的盘中 High/Low；回撤图反映价格回撤，不是含分红总回报回撤 |
| 年度买点 | 年度最高点、最低点与全年均价均需事后确认，仅用于历史情景比较，不是可在当时执行的交易信号 |
| 投资建议 | 本工具仅供研究和教育用途，不构成投资、税务或法律建议 |

## 更新代码

对 GitHub 网页方式：打开需要修改的文件，点击铅笔图标编辑后点击 **Commit changes**。对命令行方式：

```bash
git add .
git commit -m "Describe your change"
git push
```

Streamlit Community Cloud 会从 `main` 分支重新部署。

## References

[1]: https://ranaroussi.github.io/yfinance/ "yfinance documentation"
[2]: https://fred.stlouisfed.org/series/CPIAUCNS "Consumer Price Index for All Urban Consumers: All Items in U.S. City Average (CPIAUCNS) | FRED"

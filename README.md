# Stock Trading Advisory System

股票辅助决策系统 - 从选股到持仓管理的全流程解决方案。

## Features

- **AI Multi-Agent Analysis** - 基于 TradingAgents 框架，6个专业AI Agent协作分析（技术面/基本面/情绪/新闻/风险 + 多空辩论），连接 Google Gemini API
- **3-Layer Stock Screening** - 三层选股引擎：IB Market Scanner 粗筛 → finviz 基本面精筛 → AI 智能精选
- **Dual Market Support** - 美股（IB TWS + Polygon.io）+ A股（AkShare）
- **Portfolio Management** - 手动录入持仓，SQLite 存储，实时盈亏计算
- **Strategy Engine** - 结合AI分析和持仓上下文生成操作建议
- **Real-time Alerts** - 价格突破、涨跌幅、止损止盈等多条件预警
- **Scheduled Reports** - 每日/每周/每月自动生成分析报告
- **Notifications** - Telegram Bot + Email 推送

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and edit config
mkdir -p ~/.stock_trading
cp stock_trading_system/config/default_config.yaml ~/.stock_trading/config.yaml
# Edit ~/.stock_trading/config.yaml with your API keys

# Set environment variables (alternative to config file)
export GEMINI_API_KEY="your-key"
export POLYGON_API_KEY="your-key"
```

## Usage

```bash
# Analyze a stock
python -m stock_trading_system.main analyze AAPL

# Screen stocks
python -m stock_trading_system.main screen --market us --strategy growth
python -m stock_trading_system.main screen --market cn --strategy value

# Portfolio management
python -m stock_trading_system.main portfolio add AAPL 100 150.50
python -m stock_trading_system.main portfolio add 600519 200 1800.00
python -m stock_trading_system.main portfolio sell AAPL 50 180.00
python -m stock_trading_system.main portfolio list
python -m stock_trading_system.main portfolio pnl
python -m stock_trading_system.main portfolio allocation
python -m stock_trading_system.main portfolio history

# Reports
python -m stock_trading_system.main report --type daily
python -m stock_trading_system.main report --type weekly
python -m stock_trading_system.main report --type stock --ticker AAPL

# Alerts
python -m stock_trading_system.main alert add AAPL price_above 200
python -m stock_trading_system.main alert add AAPL stop_loss 140
python -m stock_trading_system.main alert list

# Start monitor (alerts + scheduled tasks)
python -m stock_trading_system.main monitor
```

## Data Sources

| Source | Market | Role | API Key |
|--------|--------|------|---------|
| IB TWS | US | Primary (real-time) | IB account |
| Polygon.io | US | Backup (free tier) | Required |
| AkShare | A-share | Primary | Not needed |
| yfinance | Global | Fallback | Not needed |
| TradingAgents | US | AI analysis data | Gemini key |

## Architecture

```
stock_trading_system/
├── config/          # YAML config + env var overrides
├── data/            # Market data providers (IB/Polygon/AkShare/yfinance)
├── agents/          # TradingAgents wrapper (Gemini-powered multi-agent)
├── screener/        # 3-layer stock screening engine
├── strategy/        # Strategy advice generation
├── portfolio/       # Position tracking + SQLite
├── alerts/          # Monitoring + Telegram/Email notifications
├── reports/         # Daily/weekly/monthly report generation
├── scheduler/       # Periodic task scheduling
└── utils/           # Logging + helpers
```

## Configuration

Edit `~/.stock_trading/config.yaml` or use environment variables:

| Env Variable | Description |
|-------------|-------------|
| `GEMINI_API_KEY` | Google Gemini API key |
| `POLYGON_API_KEY` | Polygon.io API key |
| `IB_HOST` / `IB_PORT` | IB TWS connection |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Telegram alerts |
| `EMAIL_SMTP_HOST` / `EMAIL_USERNAME` / `EMAIL_PASSWORD` | Email alerts |

## Disclaimer

This system is for **educational and research purposes only**. It provides analysis and suggestions but does NOT execute trades automatically. All investment decisions are made by the user. Not financial advice.

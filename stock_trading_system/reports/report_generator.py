"""Report generator - daily/weekly/monthly portfolio and market reports."""

import json
from datetime import datetime
from pathlib import Path

from stock_trading_system.portfolio.manager import PortfolioManager
from stock_trading_system.agents.analyzer import StockAnalyzer
from stock_trading_system.data.data_manager import DataManager
from stock_trading_system.utils import get_logger
from stock_trading_system.utils.helpers import (
    format_currency, format_percent, format_large_number, today_str,
)

logger = get_logger("reports")


class ReportGenerator:
    """Generates portfolio and analysis reports."""

    def __init__(self, config: dict):
        self._config = config
        self._pm = PortfolioManager(config)
        self._data_manager = DataManager(config)
        self._output_dir = Path(config.get("reports", {}).get("output_dir", "reports_output"))
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def daily_report(self, user_id: int) -> str:
        """Generate daily portfolio report for one tenant.

        ``user_id`` is required after hardening-iteration-v1 P1.3 — the
        prior cron path called this with no user and got a cross-tenant
        aggregate. Per-user reports must be triggered per user_id.
        """
        holdings = self._pm.get_holdings(user_id=user_id)
        pnl = self._pm.get_pnl(user_id=user_id)
        date = today_str()

        lines = [
            f"# 每日报告 - {date}",
            "",
            "## 持仓概况",
            f"- 持仓数量: {pnl['positions']}",
            f"- 总成本: {format_currency(pnl['total_cost'])}",
            f"- 总市值: {format_currency(pnl['total_value'])}",
            f"- 总盈亏: {format_currency(pnl['total_pnl'])} ({format_percent(pnl['total_pnl_pct'])})",
            "",
            "## 持仓明细",
        ]

        for h in holdings:
            pnl_style = "📈" if h["pnl"] >= 0 else "📉"
            lines.append(
                f"- {h['ticker']}: {h['shares']:.0f}股 | "
                f"成本 {format_currency(h['avg_cost'], h['market'])} | "
                f"现价 {format_currency(h['current_price'], h['market'])} | "
                f"{pnl_style} {format_currency(h['pnl'], h['market'])} ({format_percent(h['pnl_pct'])})"
            )

        report = "\n".join(lines)
        self._save_report(f"daily_{date}.md", report)
        return report

    def weekly_report(self, user_id: int) -> str:
        """Generate weekly portfolio report for one tenant."""
        holdings = self._pm.get_holdings(user_id=user_id)
        pnl = self._pm.get_pnl(user_id=user_id)
        history = self._pm.get_history(days=7, user_id=user_id)
        transactions = self._pm.get_transactions(user_id=user_id)
        date = today_str()

        lines = [
            f"# 周报 - {date}",
            "",
            "## 本周持仓概况",
            f"- 总市值: {format_currency(pnl['total_value'])}",
            f"- 总盈亏: {format_currency(pnl['total_pnl'])} ({format_percent(pnl['total_pnl_pct'])})",
            "",
        ]

        # Weekly P&L trend
        if history:
            lines.append("## 本周净值变化")
            for snap in reversed(history):
                lines.append(f"- {snap['date']}: {format_currency(snap['total_value'])} ({format_percent(snap['pnl_pct'])})")
            lines.append("")

        # Recent transactions
        week_txns = [t for t in transactions[:20]]
        if week_txns:
            lines.append("## 本周交易记录")
            for t in week_txns:
                lines.append(f"- {t['date']}: {t['action'].upper()} {t['shares']:.0f} {t['ticker']} @ {t['price']:.2f}")
            lines.append("")

        # Allocation
        allocation = self._pm.get_allocation(user_id=user_id)
        if allocation:
            lines.append("## 仓位分布")
            for item in allocation:
                lines.append(f"- {item['ticker']}: {format_percent(item['weight'] * 100)}")

        report = "\n".join(lines)
        self._save_report(f"weekly_{date}.md", report)
        return report

    def monthly_report(self, user_id: int) -> str:
        """Generate monthly portfolio report for one tenant."""
        holdings = self._pm.get_holdings(user_id=user_id)
        pnl = self._pm.get_pnl(user_id=user_id)
        history = self._pm.get_history(days=30, user_id=user_id)
        date = today_str()

        lines = [
            f"# 月报 - {date}",
            "",
            "## 月度持仓概况",
            f"- 持仓数量: {pnl['positions']}",
            f"- 总市值: {format_currency(pnl['total_value'])}",
            f"- 总盈亏: {format_currency(pnl['total_pnl'])} ({format_percent(pnl['total_pnl_pct'])})",
            "",
        ]

        # Monthly P&L trend (weekly snapshots)
        if history:
            lines.append("## 月度净值曲线")
            for snap in reversed(history[::7]):  # Show weekly points
                lines.append(f"- {snap['date']}: {format_currency(snap['total_value'])}")
            lines.append("")

        # Top winners and losers
        if holdings:
            sorted_by_pnl = sorted(holdings, key=lambda x: x["pnl_pct"], reverse=True)
            lines.append("## 持仓排行")
            lines.append("### 盈利最多")
            for h in sorted_by_pnl[:3]:
                lines.append(f"- {h['ticker']}: {format_percent(h['pnl_pct'])}")
            lines.append("### 亏损最多")
            for h in sorted_by_pnl[-3:]:
                lines.append(f"- {h['ticker']}: {format_percent(h['pnl_pct'])}")

        report = "\n".join(lines)
        self._save_report(f"monthly_{date}.md", report)
        return report

    def stock_report(self, ticker: str) -> str:
        """Generate deep analysis report for a single stock."""
        date = today_str()

        # Run full AI analysis
        analyzer = StockAnalyzer(self._config)
        try:
            result = analyzer.analyze(ticker, date)
        except Exception as e:
            return f"Analysis failed for {ticker}: {e}"

        lines = [
            f"# {ticker} 深度分析报告 - {date}",
            "",
            f"## AI 信号: {result.signal}",
            "",
            "## 技术面分析",
            result.market_report or "N/A",
            "",
            "## 基本面分析",
            result.fundamentals_report or "N/A",
            "",
            "## 情绪分析",
            result.sentiment_report or "N/A",
            "",
            "## 新闻分析",
            result.news_report or "N/A",
            "",
            "## 多空辩论",
            str(result.investment_debate) if result.investment_debate else "N/A",
            "",
            "## 风险评估",
            str(result.risk_assessment) if result.risk_assessment else "N/A",
            "",
            "## 最终决策",
            str(result.trade_decision) if result.trade_decision else "N/A",
        ]

        report = "\n".join(lines)
        self._save_report(f"stock_{ticker}_{date}.md", report)
        return report

    def _save_report(self, filename: str, content: str):
        """Save report to file."""
        path = self._output_dir / filename
        path.write_text(content, encoding="utf-8")
        logger.info("Report saved: %s", path)

"""Telegram bot - receive commands and interact with the trading system."""

import asyncio
from telegram import Update, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from stock_trading_system.config import load_config, get_config
from stock_trading_system.utils import get_logger

logger = get_logger("telegram.bot")

# Lazy-initialized components
_portfolio_mgr = None
_alert_monitor = None
_data_manager = None


def _get_portfolio_mgr():
    global _portfolio_mgr
    if _portfolio_mgr is None:
        from stock_trading_system.portfolio.manager import PortfolioManager
        _portfolio_mgr = PortfolioManager(get_config())
    return _portfolio_mgr


def _get_alert_monitor():
    global _alert_monitor
    if _alert_monitor is None:
        from stock_trading_system.alerts.monitor import AlertMonitor
        _alert_monitor = AlertMonitor(get_config())
    return _alert_monitor


def _get_data_manager():
    global _data_manager
    if _data_manager is None:
        from stock_trading_system.data.data_manager import DataManager
        _data_manager = DataManager(get_config())
    return _data_manager


def _escape_md(text: str) -> str:
    """Escape MarkdownV2 special characters."""
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


# ── Command Handlers ────────────────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "📊 *股票辅助决策系统*\n\n"
        "可用命令:\n"
        "/price <代码> \\- 查询实时价格\n"
        "/analyze <代码> \\- AI 多Agent分析\n"
        "/portfolio \\- 查看持仓\n"
        "/pnl \\- 盈亏汇总\n"
        "/buy <代码> <数量> <价格> \\- 买入记录\n"
        "/sell <代码> <数量> <价格> \\- 卖出记录\n"
        "/alert <代码> <条件> <阈值> \\- 添加预警\n"
        "/alerts \\- 查看活跃预警\n"
        "/check \\- 手动检查预警\n"
        "/screen \\[us\\|cn\\] \\[策略\\] \\- 智能选股\n"
        "/report \\[daily\\|weekly\\] \\- 生成报告\n"
        "/help \\- 帮助",
        parse_mode="MarkdownV2",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    await cmd_start(update, context)


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /price <ticker> - get current price."""
    if not context.args:
        await update.message.reply_text("用法: /price AAPL")
        return

    ticker = context.args[0].upper()
    dm = _get_data_manager()
    price = dm.get_price(ticker)

    if price:
        last = price.get("last") or price.get("close") or 0
        high = price.get("high", 0)
        low = price.get("low", 0)
        volume = price.get("volume", 0)
        text = (
            f"📈 *{_escape_md(ticker)}*\n"
            f"现价: {_escape_md(f'{last:.2f}')}\n"
            f"最高: {_escape_md(f'{high:.2f}')}  最低: {_escape_md(f'{low:.2f}')}\n"
            f"成交量: {_escape_md(f'{volume:,.0f}')}"
        )
        await update.message.reply_text(text, parse_mode="MarkdownV2")
    else:
        await update.message.reply_text(f"无法获取 {ticker} 的价格数据")


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /analyze <ticker> - run AI analysis."""
    if not context.args:
        await update.message.reply_text("用法: /analyze AAPL")
        return

    ticker = context.args[0].upper()
    await update.message.reply_text(f"🧠 正在分析 {ticker}，请稍候（约2-5分钟）...")

    try:
        from stock_trading_system.agents.analyzer import StockAnalyzer
        from stock_trading_system.utils.helpers import today_str

        analyzer = StockAnalyzer(get_config())
        result = analyzer.analyze(ticker, today_str())

        signal_emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(result.signal, "⚪")
        text = (
            f"{signal_emoji} *{_escape_md(ticker)}* 分析完成\n\n"
            f"*信号: {_escape_md(result.signal)}*\n\n"
            f"📊 *技术面:*\n{_escape_md(result.market_report[:500])}\n\n"
            f"📰 *新闻:*\n{_escape_md(result.news_report[:500])}\n\n"
            f"🏢 *基本面:*\n{_escape_md(result.fundamentals_report[:500])}"
        )
        # Telegram has 4096 char limit
        if len(text) > 4000:
            text = text[:4000] + "\\.\\.\\."
        await update.message.reply_text(text, parse_mode="MarkdownV2")
    except Exception as e:
        logger.error("Analysis failed for %s: %s", ticker, e)
        await update.message.reply_text(f"分析失败: {e}")


async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /portfolio - show current holdings."""
    pm = _get_portfolio_mgr()
    holdings = pm.get_holdings()

    if not holdings:
        await update.message.reply_text("📂 当前无持仓")
        return

    lines = ["📊 *当前持仓*\n"]
    for h in holdings:
        emoji = "📈" if h["pnl"] >= 0 else "📉"
        pnl_pct = f"+{h['pnl_pct']:.1f}" if h["pnl_pct"] >= 0 else f"{h['pnl_pct']:.1f}"
        lines.append(
            f"{emoji} *{_escape_md(h['ticker'])}*  "
            f"{_escape_md(f'{h[\"shares\"]:.0f}')}股  "
            f"成本{_escape_md(f'{h[\"avg_cost\"]:.2f}')}  "
            f"现价{_escape_md(f'{h[\"current_price\"]:.2f}')}  "
            f"{_escape_md(pnl_pct)}%"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")


async def cmd_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /pnl - P&L summary."""
    pm = _get_portfolio_mgr()
    pnl = pm.get_pnl()

    emoji = "📈" if pnl["total_pnl"] >= 0 else "📉"
    pnl_pct = f"+{pnl['total_pnl_pct']:.2f}" if pnl["total_pnl_pct"] >= 0 else f"{pnl['total_pnl_pct']:.2f}"
    text = (
        f"{emoji} *盈亏汇总*\n\n"
        f"总成本: {_escape_md(f'${pnl[\"total_cost\"]:,.2f}')}\n"
        f"总市值: {_escape_md(f'${pnl[\"total_value\"]:,.2f}')}\n"
        f"总盈亏: {_escape_md(f'${pnl[\"total_pnl\"]:,.2f}')} \\({_escape_md(pnl_pct)}%\\)\n"
        f"持仓数: {pnl['positions']}"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")


async def cmd_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /buy <ticker> <shares> <price>."""
    if len(context.args) < 3:
        await update.message.reply_text("用法: /buy AAPL 100 150.50")
        return

    ticker = context.args[0].upper()
    shares = float(context.args[1])
    price = float(context.args[2])

    from stock_trading_system.utils.helpers import detect_market
    pm = _get_portfolio_mgr()
    pm.add_position(ticker, shares, price, market=detect_market(ticker))
    await update.message.reply_text(f"✅ 买入: {shares:.0f} {ticker} @ {price:.2f}")


async def cmd_sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /sell <ticker> <shares> <price>."""
    if len(context.args) < 3:
        await update.message.reply_text("用法: /sell AAPL 50 180.00")
        return

    ticker = context.args[0].upper()
    shares = float(context.args[1])
    price = float(context.args[2])

    pm = _get_portfolio_mgr()
    pm.sell_position(ticker, shares, price)
    await update.message.reply_text(f"✅ 卖出: {shares:.0f} {ticker} @ {price:.2f}")


async def cmd_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /alert <ticker> <condition> <threshold>."""
    if len(context.args) < 3:
        await update.message.reply_text(
            "用法: /alert AAPL price_above 200\n\n"
            "条件: price_above, price_below, pct_change_above, "
            "pct_change_below, volume_spike, stop_loss, take_profit"
        )
        return

    ticker = context.args[0].upper()
    condition = context.args[1]
    threshold = float(context.args[2])

    monitor = _get_alert_monitor()
    monitor.add_alert(ticker, condition, threshold)
    await update.message.reply_text(f"🔔 预警已添加: {ticker} {condition} {threshold}")


async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /alerts - list active alerts."""
    monitor = _get_alert_monitor()
    alerts = monitor.list_alerts()

    if not alerts:
        await update.message.reply_text("🔕 当前无活跃预警")
        return

    cond_labels = {
        "price_above": "价格高于", "price_below": "价格低于",
        "pct_change_above": "涨幅超过", "pct_change_below": "跌幅超过",
        "volume_spike": "成交量超过", "stop_loss": "止损价", "take_profit": "止盈价",
    }

    lines = ["🔔 *活跃预警*\n"]
    for a in alerts:
        label = cond_labels.get(a["condition"], a["condition"])
        lines.append(f"\\#{a['id']}  *{_escape_md(a['ticker'])}*  {_escape_md(label)} {_escape_md(str(a['threshold']))}")

    await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /check - manually check alerts."""
    monitor = _get_alert_monitor()
    triggered = monitor.check_alerts()

    if triggered:
        lines = [f"🚨 触发 {len(triggered)} 条预警:\n"]
        for a in triggered:
            lines.append(f"- {a['ticker']}: {a['condition']} {a['threshold']} (现价: {a.get('current_price', 'N/A')})")
        await update.message.reply_text("\n".join(lines))
    else:
        await update.message.reply_text("✅ 无预警触发")


async def cmd_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /screen [market] [strategy]."""
    market = context.args[0] if context.args else "us"
    strategy = context.args[1] if len(context.args) > 1 else "growth"

    await update.message.reply_text(f"🔍 正在筛选 {market.upper()} 市场 ({strategy} 策略)，请稍候...")

    try:
        from stock_trading_system.screener.screener import StockScreener
        screener = StockScreener(get_config())
        results = screener.screen(market=market, strategy=strategy)

        if not results:
            await update.message.reply_text("筛选结果为空")
            return

        lines = [f"📋 *{_escape_md(market.upper())} 选股结果 \\({_escape_md(strategy)}\\)*\n"]
        for i, s in enumerate(results, 1):
            sig = s.get("signal", "N/A")
            emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(sig, "⚪")
            lines.append(f"{i}\\. {emoji} *{_escape_md(s.get('ticker', ''))}* \\- {_escape_md(sig)}")

        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:4000] + "\\.\\.\\."
        await update.message.reply_text(text, parse_mode="MarkdownV2")
    except Exception as e:
        logger.error("Screening failed: %s", e)
        await update.message.reply_text(f"筛选失败: {e}")


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /report [type]."""
    report_type = context.args[0] if context.args else "daily"

    await update.message.reply_text(f"📝 正在生成{report_type}报告...")

    try:
        from stock_trading_system.reports.report_generator import ReportGenerator
        gen = ReportGenerator(get_config())

        if report_type == "daily":
            content = gen.daily_report()
        elif report_type == "weekly":
            content = gen.weekly_report()
        elif report_type == "monthly":
            content = gen.monthly_report()
        else:
            content = gen.daily_report()

        # Send as plain text (report uses markdown that may conflict with Telegram)
        if len(content) > 4000:
            content = content[:4000] + "..."
        await update.message.reply_text(content)
    except Exception as e:
        logger.error("Report failed: %s", e)
        await update.message.reply_text(f"报告生成失败: {e}")


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle unknown commands."""
    await update.message.reply_text("未知命令，输入 /help 查看可用命令")


# ── Bot Setup ───────────────────────────────────────────────────────────────


async def post_init(application):
    """Set bot commands menu."""
    commands = [
        BotCommand("price", "查询价格 - /price AAPL"),
        BotCommand("analyze", "AI分析 - /analyze AAPL"),
        BotCommand("portfolio", "查看持仓"),
        BotCommand("pnl", "盈亏汇总"),
        BotCommand("buy", "买入 - /buy AAPL 100 150"),
        BotCommand("sell", "卖出 - /sell AAPL 50 180"),
        BotCommand("alert", "添加预警 - /alert AAPL price_above 200"),
        BotCommand("alerts", "查看预警"),
        BotCommand("check", "检查预警"),
        BotCommand("screen", "智能选股 - /screen us growth"),
        BotCommand("report", "生成报告 - /report daily"),
        BotCommand("help", "帮助"),
    ]
    await application.bot.set_my_commands(commands)


def run_bot(config_path=None):
    """Start the Telegram bot."""
    load_config(config_path)
    config = get_config()

    tg_cfg = config.get("alerts", {}).get("telegram", {})
    token = tg_cfg.get("bot_token", "")

    if not token:
        logger.error("Telegram bot_token not configured")
        print("Error: Telegram bot_token not configured in config.yaml")
        return

    logger.info("Starting Telegram bot...")

    app = ApplicationBuilder().token(token).post_init(post_init).build()

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(CommandHandler("pnl", cmd_pnl))
    app.add_handler(CommandHandler("buy", cmd_buy))
    app.add_handler(CommandHandler("sell", cmd_sell))
    app.add_handler(CommandHandler("alert", cmd_alert))
    app.add_handler(CommandHandler("alerts", cmd_alerts))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("screen", cmd_screen))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    print("Telegram Bot started. Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)

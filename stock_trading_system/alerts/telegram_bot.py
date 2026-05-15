"""Telegram bot - receive commands and interact with the trading system.

hardening-iteration-v1 P1.1 [C2]: bot is **multi-tenant** with a
chat-id → user_id whitelist. Empty `alerts.telegram.user_map` =
locked-down default (bot starts but rejects every command). Each
command resolves `update.effective_chat.id` to a registered user_id
via the cache built at startup; unknown chats get a curt rejection.
This closes the pre-P1.1 hole where any Telegram user could
/buy /sell /alert into a shared user_id=NULL "system tenant" and
/alerts /check could list every tenant's alerts.
"""

import asyncio
import functools
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

# Authorization cache populated by `_init_authz()` at bot start.
# Maps Telegram chat_id (int) → registered user_id (int).
_chat_to_user: dict[int, int] = {}


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


def _init_authz(config: dict) -> int:
    """Build the chat_id → user_id cache from config + users table.

    Returns the number of successfully resolved chats. Logs (does not
    raise) for entries that don't match a registered active user — the
    bot keeps running but those chats stay denied.
    """
    global _chat_to_user
    _chat_to_user = {}

    tg_cfg = config.get("alerts", {}).get("telegram", {})
    user_map = tg_cfg.get("user_map") or {}
    if not user_map:
        logger.warning(
            "Telegram bot started with EMPTY user_map — every command "
            "will be rejected. Populate alerts.telegram.user_map to "
            "authorize chat ids."
        )
        return 0

    db_path = config.get("portfolio", {}).get("db_path", "data/portfolio.db")
    from stock_trading_system.auth.repository import UserRepository
    repo = UserRepository(db_path)

    resolved = 0
    for raw_chat_id, email in user_map.items():
        try:
            chat_id = int(raw_chat_id)
        except (TypeError, ValueError):
            logger.error("Invalid Telegram chat_id %r in user_map", raw_chat_id)
            continue
        if not isinstance(email, str) or not email.strip():
            logger.error("Invalid email %r for chat_id=%s in user_map", email, chat_id)
            continue
        user = repo.find_by_email(email.strip().lower())
        if user is None:
            logger.error(
                "Telegram user_map[%s]=%s — no active user found, skipping",
                chat_id, email,
            )
            continue
        _chat_to_user[chat_id] = user.id
        resolved += 1
        logger.info("Telegram authz: chat_id=%s → user_id=%d (%s)",
                    chat_id, user.id, email)

    return resolved


def _resolve_user_id(chat_id: int) -> int | None:
    """Return registered user_id for ``chat_id`` or None if not authorized."""
    return _chat_to_user.get(int(chat_id))


def require_auth(handler):
    """Decorator: reject command unless chat is in the whitelist.

    Attaches the resolved user_id to ``context.user_data['user_id']`` so
    each command body just reads ``ctx.user_data['user_id']`` rather than
    re-resolving. Also logs unauthorized attempts at WARNING level so
    operators can see brute-probe patterns.
    """
    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        if chat is None:
            return
        user_id = _resolve_user_id(chat.id)
        if user_id is None:
            logger.warning(
                "Unauthorized Telegram command: chat_id=%s username=%s text=%r",
                chat.id, getattr(update.effective_user, "username", None),
                getattr(update.message, "text", None),
            )
            if update.message is not None:
                await update.message.reply_text(
                    "⛔ 此 Telegram 帐号未授权访问本 bot。请联系管理员将你的 chat id "
                    "加入 alerts.telegram.user_map。"
                )
            return
        context.user_data["user_id"] = user_id
        return await handler(update, context)
    return wrapper


def _escape_md(text: str) -> str:
    """Escape MarkdownV2 special characters."""
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


# ── Command Handlers ────────────────────────────────────────────────────────


@require_auth
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


@require_auth
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    await cmd_start(update, context)


@require_auth
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


@require_auth
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
        if len(text) > 4000:
            text = text[:4000] + "\\.\\.\\."
        await update.message.reply_text(text, parse_mode="MarkdownV2")
    except Exception as e:
        logger.error("Analysis failed for %s: %s", ticker, e)
        await update.message.reply_text(f"分析失败: {e}")


@require_auth
async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /portfolio - show current holdings for the authorized user."""
    user_id = context.user_data["user_id"]
    pm = _get_portfolio_mgr()
    holdings = pm.get_holdings(user_id=user_id)

    if not holdings:
        await update.message.reply_text("📂 当前无持仓")
        return

    lines = ["📊 *当前持仓*\n"]
    for h in holdings:
        emoji = "📈" if h["pnl"] >= 0 else "📉"
        pnl_pct = f"+{h['pnl_pct']:.1f}" if h["pnl_pct"] >= 0 else f"{h['pnl_pct']:.1f}"
        shares_s = f"{h['shares']:.0f}"
        cost_s = f"{h['avg_cost']:.2f}"
        price_s = f"{h['current_price']:.2f}"
        lines.append(
            f"{emoji} *{_escape_md(h['ticker'])}*  "
            f"{_escape_md(shares_s)}股  "
            f"成本{_escape_md(cost_s)}  "
            f"现价{_escape_md(price_s)}  "
            f"{_escape_md(pnl_pct)}%"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="MarkdownV2")


@require_auth
async def cmd_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /pnl - P&L summary for the authorized user."""
    user_id = context.user_data["user_id"]
    pm = _get_portfolio_mgr()
    pnl = pm.get_pnl(user_id=user_id)

    emoji = "📈" if pnl["total_pnl"] >= 0 else "📉"
    pnl_pct = f"+{pnl['total_pnl_pct']:.2f}" if pnl["total_pnl_pct"] >= 0 else f"{pnl['total_pnl_pct']:.2f}"
    cost_s = f"${pnl['total_cost']:,.2f}"
    value_s = f"${pnl['total_value']:,.2f}"
    pnl_s = f"${pnl['total_pnl']:,.2f}"
    text = (
        f"{emoji} *盈亏汇总*\n\n"
        f"总成本: {_escape_md(cost_s)}\n"
        f"总市值: {_escape_md(value_s)}\n"
        f"总盈亏: {_escape_md(pnl_s)} \\({_escape_md(pnl_pct)}%\\)\n"
        f"持仓数: {pnl['positions']}"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")


@require_auth
async def cmd_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /buy <ticker> <shares> <price>."""
    if len(context.args) < 3:
        await update.message.reply_text("用法: /buy AAPL 100 150.50")
        return

    ticker = context.args[0].upper()
    shares = float(context.args[1])
    price = float(context.args[2])
    user_id = context.user_data["user_id"]

    from stock_trading_system.utils.helpers import detect_market
    pm = _get_portfolio_mgr()
    pm.add_position(ticker, shares, price,
                    market=detect_market(ticker), user_id=user_id)
    await update.message.reply_text(f"✅ 买入: {shares:.0f} {ticker} @ {price:.2f}")


@require_auth
async def cmd_sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /sell <ticker> <shares> <price>."""
    if len(context.args) < 3:
        await update.message.reply_text("用法: /sell AAPL 50 180.00")
        return

    ticker = context.args[0].upper()
    shares = float(context.args[1])
    price = float(context.args[2])
    user_id = context.user_data["user_id"]

    pm = _get_portfolio_mgr()
    try:
        pm.sell_position(ticker, shares, price, user_id=user_id)
    except ValueError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    await update.message.reply_text(f"✅ 卖出: {shares:.0f} {ticker} @ {price:.2f}")


@require_auth
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
    user_id = context.user_data["user_id"]

    monitor = _get_alert_monitor()
    monitor.add_alert(ticker, condition, threshold, user_id=user_id)
    await update.message.reply_text(f"🔔 预警已添加: {ticker} {condition} {threshold}")


@require_auth
async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /alerts - list authorized user's active alerts."""
    user_id = context.user_data["user_id"]
    monitor = _get_alert_monitor()
    alerts = monitor.list_alerts(user_id=user_id, scope="user")

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


@require_auth
async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /check - manually check this user's alerts."""
    user_id = context.user_data["user_id"]
    monitor = _get_alert_monitor()
    triggered = monitor.check_alerts(user_id=user_id, scope="user")

    if triggered:
        lines = [f"🚨 触发 {len(triggered)} 条预警:\n"]
        for a in triggered:
            lines.append(f"- {a['ticker']}: {a['condition']} {a['threshold']} (现价: {a.get('current_price', 'N/A')})")
        await update.message.reply_text("\n".join(lines))
    else:
        await update.message.reply_text("✅ 无预警触发")


@require_auth
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


@require_auth
async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /report [type]."""
    report_type = context.args[0] if context.args else "daily"
    user_id = context.user_data["user_id"]

    await update.message.reply_text(f"📝 正在生成{report_type}报告...")

    try:
        from stock_trading_system.reports.report_generator import ReportGenerator
        gen = ReportGenerator(get_config())

        if report_type == "weekly":
            content = gen.weekly_report(user_id=user_id)
        elif report_type == "monthly":
            content = gen.monthly_report(user_id=user_id)
        else:
            content = gen.daily_report(user_id=user_id)

        if len(content) > 4000:
            content = content[:4000] + "..."
        await update.message.reply_text(content)
    except Exception as e:
        logger.error("Report failed: %s", e)
        await update.message.reply_text(f"报告生成失败: {e}")


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle unknown commands. Not wrapped in @require_auth so
    unauthorized users still see a friendly 'unknown command' message
    rather than getting silently dropped."""
    chat = update.effective_chat
    if chat is not None and _resolve_user_id(chat.id) is None:
        # Don't even reveal which commands exist.
        logger.warning("Unauthorized unknown command from chat_id=%s", chat.id)
        return
    if update.message is not None:
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

    authorized = _init_authz(config)
    logger.info("Telegram bot authz: %d chat(s) whitelisted", authorized)

    logger.info("Starting Telegram bot...")

    app = ApplicationBuilder().token(token).post_init(post_init).build()

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

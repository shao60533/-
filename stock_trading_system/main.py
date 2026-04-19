"""CLI entry point for Stock Trading Advisory System."""

import os

import click
from rich.console import Console
from rich.table import Table

from stock_trading_system.config import load_config, get_config
from stock_trading_system.utils import get_logger

console = Console()
logger = get_logger("main")


@click.group()
@click.option("--config", "config_path", default=None, help="Path to config YAML file")
def cli(config_path):
    """Stock Trading Advisory System - 股票辅助决策系统"""
    load_config(config_path)


# ── analyze ──────────────────────────────────────────────────────────────────


@cli.command()
@click.argument("ticker")
@click.option("--date", default=None, help="Analysis date (YYYY-MM-DD), defaults to today")
def analyze(ticker, date):
    """Analyze a stock using multi-agent AI analysis."""
    from stock_trading_system.agents.analyzer import StockAnalyzer
    from stock_trading_system.utils.helpers import today_str

    date = date or today_str()
    config = get_config()

    console.print(f"\n[bold cyan]Analyzing {ticker.upper()} for {date}...[/bold cyan]\n")

    analyzer = StockAnalyzer(config)
    result = analyzer.analyze(ticker.upper(), date)

    # Display results
    console.print(f"[bold green]Signal: {result.signal}[/bold green]\n")
    console.print("[bold]Technical Analysis:[/bold]")
    console.print(result.market_report)
    console.print("\n[bold]Fundamentals:[/bold]")
    console.print(result.fundamentals_report)
    console.print("\n[bold]Sentiment:[/bold]")
    console.print(result.sentiment_report)
    console.print("\n[bold]News:[/bold]")
    console.print(result.news_report)
    console.print("\n[bold]Investment Debate:[/bold]")
    console.print(str(result.investment_debate))
    console.print("\n[bold]Risk Assessment:[/bold]")
    console.print(str(result.risk_assessment))
    console.print("\n[bold]Final Decision:[/bold]")
    console.print(str(result.trade_decision))


# ── screen ───────────────────────────────────────────────────────────────────


@cli.command()
@click.option("--market", type=click.Choice(["us", "cn", "all"]), default="us", help="Market to screen")
@click.option("--strategy", type=click.Choice(["growth", "value", "momentum", "low_volatility"]), default="growth")
def screen(market, strategy):
    """Screen stocks using 3-layer filtering (IB Scanner + finviz + AI)."""
    from stock_trading_system.screener.screener import StockScreener

    config = get_config()
    screener = StockScreener(config)

    console.print(f"\n[bold cyan]Screening {market.upper()} market with '{strategy}' strategy...[/bold cyan]\n")

    results = screener.screen(market=market, strategy=strategy)

    table = Table(title=f"Top Picks - {market.upper()} ({strategy})")
    table.add_column("Rank", style="dim", width=4)
    table.add_column("Ticker", style="cyan bold")
    table.add_column("Name")
    table.add_column("Price", justify="right")
    table.add_column("Signal", justify="center")
    table.add_column("Summary")

    for i, stock in enumerate(results, 1):
        table.add_row(
            str(i),
            stock.get("ticker", ""),
            stock.get("name", ""),
            stock.get("price", ""),
            stock.get("signal", ""),
            stock.get("summary", ""),
        )

    console.print(table)


# ── portfolio ────────────────────────────────────────────────────────────────


@cli.group()
def portfolio():
    """Manage your portfolio (manual entry)."""
    pass


@portfolio.command("add")
@click.argument("ticker")
@click.argument("shares", type=float)
@click.argument("price", type=float)
@click.option("--date", default=None, help="Transaction date (YYYY-MM-DD)")
@click.option("--notes", default="", help="Transaction notes")
def portfolio_add(ticker, shares, price, date, notes):
    """Add a buy transaction. Example: portfolio add AAPL 100 150.50"""
    from stock_trading_system.portfolio.manager import PortfolioManager
    from stock_trading_system.utils.helpers import detect_market

    config = get_config()
    pm = PortfolioManager(config)
    market = detect_market(ticker)
    pm.add_position(ticker.upper(), shares, price, market=market, date=date, notes=notes)
    console.print(f"[green]Added: BUY {shares} {ticker.upper()} @ {price}[/green]")


@portfolio.command("sell")
@click.argument("ticker")
@click.argument("shares", type=float)
@click.argument("price", type=float)
@click.option("--date", default=None, help="Transaction date (YYYY-MM-DD)")
@click.option("--notes", default="", help="Transaction notes")
def portfolio_sell(ticker, shares, price, date, notes):
    """Record a sell transaction. Example: portfolio sell AAPL 50 180.00"""
    from stock_trading_system.portfolio.manager import PortfolioManager

    config = get_config()
    pm = PortfolioManager(config)
    pm.sell_position(ticker.upper(), shares, price, date=date, notes=notes)
    console.print(f"[yellow]Sold: SELL {shares} {ticker.upper()} @ {price}[/yellow]")


@portfolio.command("list")
def portfolio_list():
    """Show current holdings with real-time P&L."""
    from stock_trading_system.portfolio.manager import PortfolioManager
    from stock_trading_system.utils.helpers import format_currency, format_percent

    config = get_config()
    pm = PortfolioManager(config)
    holdings = pm.get_holdings()

    if not holdings:
        console.print("[dim]No positions in portfolio.[/dim]")
        return

    table = Table(title="Current Holdings")
    table.add_column("Ticker", style="cyan bold")
    table.add_column("Market")
    table.add_column("Shares", justify="right")
    table.add_column("Avg Cost", justify="right")
    table.add_column("Current", justify="right")
    table.add_column("P&L", justify="right")
    table.add_column("P&L %", justify="right")

    for h in holdings:
        pnl_style = "green" if h.get("pnl", 0) >= 0 else "red"
        table.add_row(
            h["ticker"],
            h["market"],
            f"{h['shares']:.0f}",
            format_currency(h["avg_cost"], h["market"]),
            format_currency(h.get("current_price", 0), h["market"]),
            f"[{pnl_style}]{format_currency(h.get('pnl', 0), h['market'])}[/{pnl_style}]",
            f"[{pnl_style}]{format_percent(h.get('pnl_pct', 0))}[/{pnl_style}]",
        )

    console.print(table)


@portfolio.command("history")
@click.option("--ticker", default=None, help="Filter by ticker")
def portfolio_history(ticker):
    """Show transaction history."""
    from stock_trading_system.portfolio.manager import PortfolioManager

    config = get_config()
    pm = PortfolioManager(config)
    transactions = pm.get_transactions(ticker=ticker)

    table = Table(title="Transaction History")
    table.add_column("Date", style="dim")
    table.add_column("Action")
    table.add_column("Ticker", style="cyan")
    table.add_column("Shares", justify="right")
    table.add_column("Price", justify="right")
    table.add_column("Notes")

    for t in transactions:
        action_style = "green" if t["action"] == "buy" else "yellow"
        table.add_row(
            t["date"],
            f"[{action_style}]{t['action'].upper()}[/{action_style}]",
            t["ticker"],
            f"{t['shares']:.0f}",
            f"{t['price']:.2f}",
            t.get("notes", ""),
        )

    console.print(table)


@portfolio.command("pnl")
def portfolio_pnl():
    """Show profit & loss summary."""
    from stock_trading_system.portfolio.manager import PortfolioManager
    from stock_trading_system.utils.helpers import format_currency, format_percent

    config = get_config()
    pm = PortfolioManager(config)
    pnl = pm.get_pnl()

    console.print("\n[bold]Portfolio P&L Summary[/bold]")
    console.print(f"  Total Cost:    {format_currency(pnl['total_cost'])}")
    console.print(f"  Total Value:   {format_currency(pnl['total_value'])}")
    pnl_style = "green" if pnl["total_pnl"] >= 0 else "red"
    console.print(f"  Total P&L:     [{pnl_style}]{format_currency(pnl['total_pnl'])} ({format_percent(pnl['total_pnl_pct'])})[/{pnl_style}]")


@portfolio.command("allocation")
def portfolio_allocation():
    """Show position allocation breakdown."""
    from stock_trading_system.portfolio.manager import PortfolioManager
    from stock_trading_system.utils.helpers import format_percent

    config = get_config()
    pm = PortfolioManager(config)
    allocation = pm.get_allocation()

    console.print("\n[bold]Position Allocation[/bold]")
    for item in allocation:
        bar_len = int(item["weight"] * 40)
        bar = "█" * bar_len
        console.print(f"  {item['ticker']:>8s}  {bar}  {format_percent(item['weight'] * 100)}")


# ── report ───────────────────────────────────────────────────────────────────


@cli.command()
@click.option("--type", "report_type", type=click.Choice(["daily", "weekly", "monthly", "stock"]), default="daily")
@click.option("--ticker", default=None, help="Ticker for stock report")
def report(report_type, ticker):
    """Generate analysis reports."""
    from stock_trading_system.reports.report_generator import ReportGenerator

    config = get_config()
    gen = ReportGenerator(config)

    if report_type == "stock" and not ticker:
        console.print("[red]Error: --ticker required for stock report[/red]")
        return

    console.print(f"\n[bold cyan]Generating {report_type} report...[/bold cyan]\n")

    if report_type == "daily":
        content = gen.daily_report()
    elif report_type == "weekly":
        content = gen.weekly_report()
    elif report_type == "monthly":
        content = gen.monthly_report()
    else:
        content = gen.stock_report(ticker.upper())

    console.print(content)


# ── alert ────────────────────────────────────────────────────────────────────


@cli.group()
def alert():
    """Manage price and indicator alerts."""
    pass


@alert.command("add")
@click.argument("ticker")
@click.argument("condition", type=click.Choice([
    "price_above", "price_below",
    "pct_change_above", "pct_change_below",
    "volume_spike",
    "stop_loss", "take_profit",
]))
@click.argument("threshold", type=float)
def alert_add(ticker, condition, threshold):
    """Add an alert. Example: alert add AAPL price_above 200"""
    from stock_trading_system.alerts.monitor import AlertMonitor

    config = get_config()
    monitor = AlertMonitor(config)
    monitor.add_alert(ticker.upper(), condition, threshold)
    console.print(f"[green]Alert added: {ticker.upper()} {condition} {threshold}[/green]")


@alert.command("list")
def alert_list():
    """List all active alerts."""
    from stock_trading_system.alerts.monitor import AlertMonitor

    config = get_config()
    monitor = AlertMonitor(config)
    alerts = monitor.list_alerts()

    table = Table(title="Active Alerts")
    table.add_column("ID", style="dim")
    table.add_column("Ticker", style="cyan")
    table.add_column("Condition")
    table.add_column("Threshold", justify="right")
    table.add_column("Created")

    for a in alerts:
        table.add_row(str(a["id"]), a["ticker"], a["condition"], str(a["threshold"]), a["created"])

    console.print(table)


@alert.command("remove")
@click.argument("alert_id", type=int)
def alert_remove(alert_id):
    """Remove an alert by ID."""
    from stock_trading_system.alerts.monitor import AlertMonitor

    config = get_config()
    monitor = AlertMonitor(config)
    monitor.remove_alert(alert_id)
    console.print(f"[yellow]Alert {alert_id} removed.[/yellow]")


# ── monitor ──────────────────────────────────────────────────────────────────


@cli.command()
def monitor():
    """Start real-time monitoring (alerts + scheduled tasks)."""
    from stock_trading_system.scheduler.task_scheduler import TaskScheduler

    config = get_config()
    scheduler = TaskScheduler(config)

    console.print("[bold cyan]Starting monitor... Press Ctrl+C to stop.[/bold cyan]")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        console.print("\n[yellow]Monitor stopped.[/yellow]")


# ── web ─────────────────────────────────────────────────────────────────────


@cli.command()
<<<<<<< HEAD
@click.option("--host", default="0.0.0.0", help="Bind host")
@click.option("--port", default=None, type=int,
              help="Bind port (defaults to $PORT env or 5000)")
=======
@click.option(
    "--host",
    default=lambda: os.environ.get("HOST", "0.0.0.0"),
    help="Bind host (env: HOST, default: 0.0.0.0)",
)
@click.option(
    "--port",
    default=lambda: int(os.environ.get("PORT", "5000")),
    type=int,
    help="Bind port (env: PORT, default: 5000)",
)
>>>>>>> origin/claude/stock-trading-system-LXzEI
@click.option("--debug", is_flag=True, help="Enable debug mode")
def web(host, port, debug):
    """Start web dashboard server."""
    import os
    from stock_trading_system.web.app import run_app

    if port is None:
        port = int(os.environ.get("PORT", 5000))

    console.print(f"[bold cyan]Starting web dashboard at http://{host}:{port}[/bold cyan]")
    run_app(host=host, port=port, debug=debug)


# ── bot ─────────────────────────────────────────────────────────────────────


@cli.command()
def bot():
    """Start Telegram bot for remote control."""
    from stock_trading_system.alerts.telegram_bot import run_bot

    console.print("[bold cyan]Starting Telegram bot...[/bold cyan]")
    run_bot()


def main():
    cli()


if __name__ == "__main__":
    main()

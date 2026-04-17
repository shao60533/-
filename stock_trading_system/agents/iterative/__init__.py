"""Self-iterating agent evolution module.

Wraps the TradingAgents 7-agent pipeline with three evolution layers:
1. Agent Scorer  — per-agent signal tracking + performance metrics
2. Darwinian     — weight adjustment based on rolling Sharpe
3. Meta Agent    — prompt rewriting for underperformers (Phase 3)
"""

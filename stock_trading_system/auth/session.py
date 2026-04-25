"""Flask session management for user authentication."""

from __future__ import annotations

from flask import session, g

from stock_trading_system.auth.repository import UserRepository

SESSION_KEY = "user_id"
SESSION_VERSION_KEY = "sv"
CURRENT_SESSION_VERSION = 1


def login_user(user_id: int) -> None:
    """Set session for authenticated user."""
    session.clear()
    session[SESSION_KEY] = user_id
    session[SESSION_VERSION_KEY] = CURRENT_SESSION_VERSION
    session.permanent = True  # 30-day sliding


def logout_user() -> None:
    """Clear session."""
    session.clear()


def load_current_user(repo: UserRepository) -> None:
    """Called from before_request. Populates g.user or None."""
    g.user = None
    uid = session.get(SESSION_KEY)
    sv = session.get(SESSION_VERSION_KEY)
    if uid is None or sv != CURRENT_SESSION_VERSION:
        return
    user = repo.find_by_id(uid)
    if user and user.status == "active":
        g.user = user

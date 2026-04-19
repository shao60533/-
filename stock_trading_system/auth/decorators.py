"""Access control decorators."""

from __future__ import annotations

from functools import wraps

from flask import g, abort, redirect, request, jsonify, url_for


def login_required(fn):
    """Require an authenticated user. Returns 401 for API, redirects for pages."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if g.get("user") is None:
            if request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized"}), 401
            return redirect("/login?next=" + request.path)
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    """Require an admin user. Returns 403 for non-admins."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        u = g.get("user")
        if u is None or u.role != "admin":
            if request.path.startswith("/api/"):
                return jsonify({"error": "forbidden"}), 403
            abort(403)
        return fn(*args, **kwargs)
    return wrapper

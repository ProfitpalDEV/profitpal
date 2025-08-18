# security.py
from fastapi import Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
from datetime import datetime, timedelta, timezone
import sqlite3, secrets
from typing import Optional, Dict

SESSION_COOKIE = "pp_session"
CSRF_COOKIE   = "pp_csrf"

# >>> Путь к ОСНОВНОЙ БД (где таблица users)
DB_PATH = "profitpal.db"

def _db():
    con = sqlite3.connect(DB_PATH)   # важно: используем DB_PATH
    con.row_factory = sqlite3.Row
    return con

def create_session(user_id: int, ip: str, ua: str, days: int = 30):
    """Create server-side session and return (token, csrf, expires_iso)."""
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with _db() as con:
        con.execute(
            "INSERT INTO user_sessions (user_id, session_token, expires_at, ip_address, user_agent, is_active) "
            "VALUES (?, ?, ?, ?, ?, 1)",
            (user_id, token, expires_at, ip, ua),
        )
    return token, csrf, expires_at

def _fetch_user_by_session(token: str) -> Optional[Dict]:
    if not token:
        return None
    with _db() as con:
        row = con.execute(
            """
            SELECT u.id, u.license_key, u.plan_type, u.subscription_status, u.is_active
            FROM user_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.session_token = ?
              AND s.is_active = 1
              AND s.expires_at > datetime('now')
            """,
            (token,),
        ).fetchone()
    return dict(row) if row else None

def _plan_rank(plan: str) -> int:
    order = {"lifetime": 1, "early_bird": 1, "standard": 2, "pro": 3}
    return order.get(plan, 0)

async def require_user(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    user = _fetch_user_by_session(token)
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    request.state.user = user
    return user

def require_plan(min_plan: str):
    """Dependency: ensures user has active subscription and required plan tier."""
    async def _inner(request: Request, user = Depends(require_user)):
        if user.get("subscription_status") not in ("active",):
            raise HTTPException(status_code=402, detail="Payment Required")
        if _plan_rank(user.get("plan_type")) < _plan_rank(min_plan):
            raise HTTPException(status_code=403, detail="Insufficient plan")
        return user
    return _inner

def verify_csrf(request: Request):
    """Double-submit cookie CSRF: header must match cookie."""
    header = request.headers.get("X-CSRF-Token")
    cookie = request.cookies.get(CSRF_COOKIE)
    if not header or not cookie or header != cookie:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

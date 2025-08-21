# security.py
from fastapi import Request, HTTPException, Response
from datetime import datetime, timedelta, timezone
import sqlite3
import secrets
import os
from typing import Optional, Dict

# ---- cookie names ----
SESSION_COOKIE = "pp_session"
CSRF_COOKIE    = "pp_csrf"

# ---- single DB path (совпадает с auth_manager) ----
DB_PATH = "profitpal_auth.db"

# ---- admin bypass via ENV ----
ADMIN_EMAIL        = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
ADMIN_LICENSE_KEY  = (os.getenv("ADMIN_LICENSE_KEY") or "").strip()
ADMIN_FULL_NAME    = (os.getenv("ADMIN_FULL_NAME") or "System Administrator").strip()

def _db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def create_session(user_id: int, ip: str, ua: str, days: int = 30):
    """Create server-side session in DB and return (token, csrf, expires_iso)."""
    token = secrets.token_urlsafe(32)
    csrf  = secrets.token_urlsafe(24)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with _db() as con:
        con.execute(
            "INSERT INTO user_sessions (user_id, session_token, expires_at, ip_address, user_agent, is_active) "
            "VALUES (?, ?, ?, ?, ?, 1)",
            (user_id, token, expires_at, ip, ua),
        )
    return token, csrf, expires_at

def set_session_cookies(
    response: Response,
    request: Request,
    token: str,
    csrf: str,
    days: int = 30,
    secure: bool | None = None,
):
    """
    Ставит pp_session (HttpOnly) и pp_csrf на корректный домен.
    Для apex/сабдоменов profitpal → ставим Domain=.profitpal.org.
    """
    host = (request.url.hostname or "").lower()
    cookie_domain = None
    if host.endswith("profitpal.org"):
        cookie_domain = ".profitpal.org"

    if secure is None:
        secure = (request.url.scheme == "https")

    max_age = days * 24 * 3600

    # session cookie (HttpOnly)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=max_age,
        path="/",
        domain=cookie_domain,
        secure=secure,
        httponly=True,
        samesite="Lax",
    )

    # csrf cookie (доступна JS)
    response.set_cookie(
        key=CSRF_COOKIE,
        value=csrf,
        max_age=max_age,
        path="/",
        domain=cookie_domain,
        secure=secure,
        httponly=False,
        samesite="Lax",
    )

def _fetch_user_by_session(token: str) -> Optional[Dict]:
    """Return user dict by session token or None (без исключений/500)."""
    if not token:
        return None
    try:
        with _db() as con:
            row = con.execute(
                """
                SELECT u.id, u.license_key, u.is_active, u.payment_status, u.email
                FROM user_sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.session_token = ?
                  AND s.is_active = 1
                  AND s.expires_at > datetime('now')
                """,
                (token,),
            ).fetchone()
            if not row:
                return None
    except Exception:
        return None

    # нормализуем план/подписку
    plan_type = None
    sub = None
    ps = (row["payment_status"] or "").lower() if "payment_status" in row.keys() else ""
    if ps in ("completed", "active", "paid"):
        plan_type = "lifetime"
        sub = "active"

    return {
        "id": row["id"],
        "email": row["email"] if "email" in row.keys() else None,
        "license_key": row["license_key"],
        "is_active": row["is_active"],
        "plan_type": plan_type,
        "subscription_status": sub,
    }

def _plan_rank(plan: Optional[str]) -> int:
    order = {"lifetime": 3, "pro": 2, "standard": 1, "early_bird": 1}
    return order.get((plan or "").lower(), 0)

async def require_user(request: Request):
    """401 вместо 500 при любых проблемах."""
    try:
        token = request.cookies.get(SESSION_COOKIE)
        user = _fetch_user_by_session(token)
        if not user or not user.get("is_active"):
            raise HTTPException(status_code=401, detail="Unauthorized")
        request.state.user = user
        return user
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Unauthorized")

def require_plan(required: Optional[str] = None):
    """Админ по ENV проходит всегда; иначе проверяем план/подписку."""
    async def _dep(request: Request):
        user = await require_user(request)

        # admin bypass
        email = (user.get("email") or "").strip().lower()
        if ADMIN_EMAIL and email == ADMIN_EMAIL:
            return user

        if not required:
            return user

        need = _plan_rank(required)
        have = _plan_rank(user.get("plan_type"))
        subs = (user.get("subscription_status") or "").lower()

        if not ((have >= need) or (subs in ("active", "trialing"))):
            raise HTTPException(status_code=402, detail="Payment required")
        return user
    return _dep

def verify_csrf(request: Request):
    """Double-submit cookie CSRF: header X-CSRF-Token должен совпадать с кукой."""
    hdr = request.headers.get("X-CSRF-Token")
    ckv = request.cookies.get(CSRF_COOKIE)
    if not hdr or not ckv or hdr != ckv:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
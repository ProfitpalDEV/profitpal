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
    if not token:
        return None
    try:
        with _db() as con:
            row = con.execute(
                """
                SELECT u.id, u.is_active
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

            uid = int(row["id"])
            is_active = int(row["is_active"] or 0)

            cols = {c[1] for c in con.execute("PRAGMA table_info(users)").fetchall()}

            email = None
            if "email" in cols:
                r = con.execute("SELECT email FROM users WHERE id = ?", (uid,)).fetchone()
                if r:
                    email = r["email"]

            payment_status = None
            if "payment_status" in cols:
                r = con.execute("SELECT payment_status FROM users WHERE id = ?", (uid,)).fetchone()
                if r:
                    payment_status = r["payment_status"]

            # ⬇️ ДОБАВЬ ЭТО: license_key (если колонка есть)
            license_key = None
            if "license_key" in cols:
                r = con.execute("SELECT license_key FROM users WHERE id = ?", (uid,)).fetchone()
                if r:
                    license_key = r["license_key"]

    except Exception as e:
        print(f"[security] _fetch_user_by_session error: {type(e).__name__}: {e}")
        return None

    plan_type = None
    subscription_status = None
    if payment_status is not None:
        ps = str(payment_status).lower()
        if ps in ("completed", "active", "paid"):
            plan_type = "lifetime"
            subscription_status = "active"
        else:
            subscription_status = "inactive"

    return {
        "id": uid,
        "email": email,                # может быть None — ок
        "license_key": license_key,    # ⬅️ понадобится для is_admin
        "is_active": is_active,
        "plan_type": plan_type,
        "subscription_status": subscription_status,
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
    async def _inner(request: Request):
        user = await require_user(request)

        email = (user.get("email") or "").strip().lower()
        is_admin = bool(ADMIN_EMAIL and email == ADMIN_EMAIL)

        if not is_admin and ADMIN_EMAIL:
            try:
                from auth_manager import auth_manager as AUTH
                admin_row = AUTH.get_user_by_email(ADMIN_EMAIL)
                if admin_row and int(admin_row.get("id", 0)) == int(user.get("id", 0)):
                    is_admin = True
            except Exception as e:
                print(f"[security] admin id fallback error: {e}")

        if is_admin:
            return user

        if not required:
            return user

        need = _plan_rank(required)
        have = _plan_rank(user.get("plan_type"))
        subs = (user.get("subscription_status") or "").lower()

        if (have >= need) or (subs in ("active", "trialing")):
            return user
        raise HTTPException(status_code=402, detail="Payment required")
    return _inner
    

def verify_csrf(request: Request):
    """Double-submit cookie CSRF: header X-CSRF-Token должен совпадать с кукой."""
    hdr = request.headers.get("X-CSRF-Token")
    ckv = request.cookies.get(CSRF_COOKIE)
    if not hdr or not ckv or hdr != ckv:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
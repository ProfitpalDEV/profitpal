# === ВЕРХ ФАЙЛА ===
from fastapi import Request, HTTPException, Response
import sqlite3
import secrets
import os
from typing import Optional, Dict
from datetime import datetime, timedelta, timezone

SESSION_COOKIE = "pp_session"
CSRF_COOKIE    = "pp_csrf"
DB_PATH = "profitpal_auth.db"
ADMIN_EMAIL = (os.getenv("ADMIN_EMAIL", "").strip().lower() or "")

def _db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def create_session(user_id: int, ip: str, ua: str, days: int = 30):
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
    """Ставит pp_session / pp_csrf на нужный домен (.profitpal.org)."""
    cookie_domain = request.url.hostname or None
    if cookie_domain and cookie_domain.endswith("profitpal.org"):
        cookie_domain = ".profitpal.org"

    if secure is None:
        secure = (request.url.scheme == "https")

    max_age = days * 24 * 3600

    response.set_cookie(
        key=SESSION_COOKIE, value=token,
        max_age=max_age, path="/",
        httponly=True, secure=secure, samesite="Lax",
        domain=cookie_domain,
    )
    response.set_cookie(
        key=CSRF_COOKIE, value=csrf,
        max_age=max_age, path="/",
        httponly=False, secure=secure, samesite="Lax",
        domain=cookie_domain,
    )
    print(f"[auth] cookies set for host={request.url.hostname} domain={cookie_domain} secure={secure} token={token[:8]}...")

def _fetch_user_by_session(token: str) -> Optional[Dict]:
    """Безопасно достаёт пользователя по токену сессии. Возвращает None, если не найден / истёк."""
    if not token:
        return None
    try:
        with _db() as con:
            row = con.execute(
                """
                SELECT u.id, u.email, u.license_key, u.is_active
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

            # опционально — достаём payment_status, если поле есть
            payment_status = None
            try:
                ps = con.execute(
                    "SELECT payment_status FROM users WHERE id = ?",
                    (row["id"],),
                ).fetchone()
                if ps and "payment_status" in ps.keys():
                    payment_status = ps["payment_status"]
            except sqlite3.OperationalError:
                payment_status = None
    except Exception as e:
        print(f"[security] _fetch_user_by_session error: {e}")
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
        "id": row["id"],
        "email": row["email"],
        "license_key": row["license_key"],
        "is_active": row["is_active"],
        "plan_type": plan_type,
        "subscription_status": subscription_status,
    }

def _plan_rank(plan: Optional[str]) -> int:
    return {"lifetime": 3, "pro": 2, "standard": 1, "early_bird": 1}.get((plan or "").lower(), 0)

async def require_user(request: Request):
    """401 вместо 500 при любых проблемах с сессией."""
    try:
        token = request.cookies.get(SESSION_COOKIE)
        user = _fetch_user_by_session(token)
        if not user or not user.get("is_active"):
            raise HTTPException(status_code=401, detail="Unauthorized")
        request.state.user = user
        return user
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ require_user error: {type(e).__name__}: {e}")
        raise HTTPException(status_code=401, detail="Unauthorized")

def require_plan(required: Optional[str] = None):
    """
    Депенденси для маршрутов: сначала валидируем сессию,
    для ADMIN_EMAIL делаем байпас, для остальных проверяем план/подписку.
    """
    async def _inner(request: Request):
        # 1) проверяем, что сессия валидна (401 если нет)
        user = await require_user(request)

        # 2) админ всегда проходит
        email = (user.get("email") or "").strip().lower()
        if ADMIN_EMAIL and email == ADMIN_EMAIL:
            return user

        # 3) если маршрут не требует конкретного плана — пускаем
        if not required:
            return user

        # 4) проверяем план/подписку
        need = _plan_rank(required)
        have = _plan_rank(user.get("plan_type"))
        subs = (user.get("subscription_status") or "").lower()

        if (have >= need) or (subs in ("active", "trialing")):
            return user

        # иначе 402 Payment Required
        raise HTTPException(status_code=402, detail="Payment required")

    return _inner

def verify_csrf(request: Request):
    header = request.headers.get("X-CSRF-Token")
    cookie = request.cookies.get(CSRF_COOKIE)
    if not header or not cookie or header != cookie:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
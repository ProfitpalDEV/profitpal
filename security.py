# security.py
from fastapi import Request, HTTPException
from datetime import datetime, timedelta, timezone
import sqlite3, secrets, os
from typing import Optional, Dict

# Куки
SESSION_COOKIE = "pp_session"
CSRF_COOKIE    = "pp_csrf"

# БД такая же, как в auth_manager
DB_PATH = "profitpal_auth.db"

# Админ из ENV (для байпаса require_plan)
ADMIN_EMAIL = (os.getenv("ADMIN_EMAIL", "").strip().lower() or "")

def _db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def create_session(user_id: int, ip: str, ua: str, days: int = 30):
    """Создаёт серверную сессию и возвращает (token, csrf, expires_iso)."""
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

def _fetch_user_by_session(token: str) -> Optional[Dict]:
    """Достаёт пользователя по токену сессии. План/подписка — опциональны."""
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

            # попробуем получить payment_status, если такая колонка есть
            payment_status = None
            try:
                r2 = con.execute("SELECT payment_status FROM users WHERE id = ?", (row["id"],)).fetchone()
                if r2 and "payment_status" in r2.keys():
                    payment_status = r2["payment_status"]
            except sqlite3.OperationalError:
                pass
    except sqlite3.OperationalError as e:
        print(f"[security] _fetch_user_by_session schema error: {e}")
        return None

    # по умолчанию плана/подписки нет
    plan_type = None
    subscription_status = None

    # если есть payment_status — нормализуем
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
        "plan_type": plan_type,                  # None | "lifetime"
        "subscription_status": subscription_status,  # None | "active" | "inactive"
    }

def _plan_rank(plan: Optional[str]) -> int:
    # lifetime — самый высокий ранг
    order = {"lifetime": 3, "pro": 2, "standard": 1, "early_bird": 1}
    return order.get((plan or "").lower(), 0)

async def require_user(request: Request):
    """Пускаем только при валидной активной сессии (без 500)."""
    try:
        token = request.cookies.get(SESSION_COOKIE)
        if not token:
            raise HTTPException(status_code=401, detail="No session")
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
    Требует план/подписку. Админ из ENV проходит всегда.
    Любые ошибки отдаются как 401/402, а не 500.
    """
    async def _dep(request: Request):
        user = await require_user(request)

        # ✅ админ-байпас
        email = (user.get("email") or "").strip().lower()
        if ADMIN_EMAIL and email == ADMIN_EMAIL:
            return user

        if not required:
            return user

        need = _plan_rank(required)
        have = _plan_rank(user.get("plan_type"))
        subs = (user.get("subscription_status") or "").lower()

        ok = (have >= need) or (subs in ("active", "trialing"))
        if not ok:
            raise HTTPException(status_code=402, detail="Payment required")

        return user
    return _dep

def verify_csrf(request: Request):
    """Double-submit cookie CSRF: заголовок должен совпадать с cookie."""
    header = request.headers.get("X-CSRF-Token")
    cookie = request.cookies.get(CSRF_COOKIE)
    if not header or not cookie or header != cookie:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
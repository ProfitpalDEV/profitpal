# security.py
from fastapi import Request, HTTPException, Depends
from datetime import datetime, timedelta, timezone
import sqlite3, secrets
from typing import Optional, Dict

# Куки
SESSION_COOKIE = "pp_session"
CSRF_COOKIE    = "pp_csrf"

# ВАЖНО: используем ту же БД, что и auth_manager (где таблица users)
DB_PATH = "profitpal_auth.db"

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
    """Достаём пользователя по токену сессии. План/подписка — опциональны."""
    if not token:
        return None

    with _db() as con:
        # базовые поля, которые точно есть
        row = con.execute(
            """
            SELECT u.id, u.license_key, u.is_active
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

        # пробуем получить payment_status, если такая колонка есть
        payment_status = None
        try:
            r2 = con.execute("SELECT payment_status FROM users WHERE id = ?", (row["id"],)).fetchone()
            if r2 and "payment_status" in r2.keys():
                payment_status = r2["payment_status"]
        except sqlite3.OperationalError:
            # колонки payment_status нет — тихо игнорируем
            pass

    # по умолчанию полей плана/подписки нет
    plan_type = None
    subscription_status = None

    # если есть payment_status — нормализуем
    if payment_status is not None:
        ps = str(payment_status).lower()
        if ps in ("completed", "active", "paid"):
            plan_type = "lifetime"          # чтобы require_plan("lifetime") проходил
            subscription_status = "active"
        else:
            subscription_status = "inactive"

    return {
        "id": row["id"],
        "license_key": row["license_key"],
        "is_active": row["is_active"],
        "plan_type": plan_type,                   # None или "lifetime"
        "subscription_status": subscription_status,  # None / "active" / "inactive"
    }


def _plan_rank(plan: Optional[str]) -> int:
    order = {"lifetime": 1, "early_bird": 1, "standard": 2, "pro": 3}
    return order.get((plan or "").lower(), 0)

async def require_user(request: Request):
    """Пускаем только при валидной активной сессии."""
    token = request.cookies.get(SESSION_COOKIE)
    user = _fetch_user_by_session(token)
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    request.state.user = user
    return user

def require_plan(min_plan: str):
    """
    Требует определённый план. Если колонок plan/subscription нет в БД —
    gracefully разрешаем доступ активному пользователю.
    """
    async def _inner(request: Request, user = Depends(require_user)):
        subs = user.get("subscription_status")
        plan = user.get("plan_type")

        # Нет полей в БД → разрешаем активному пользователю
        if subs is None and plan is None:
            return user

        if subs not in ("active", "trialing"):
            raise HTTPException(status_code=402, detail="Payment Required")

        if _plan_rank(plan) < _plan_rank(min_plan):
            raise HTTPException(status_code=403, detail="Insufficient plan")

        return user
    return _inner

def verify_csrf(request: Request):
    """Double-submit cookie CSRF: заголовок должен совпадать с cookie."""
    header = request.headers.get("X-CSRF-Token")
    cookie = request.cookies.get(CSRF_COOKIE)
    if not header or not cookie or header != cookie:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

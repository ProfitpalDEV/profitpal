# security.py
from fastapi import Request, HTTPException, Response
from datetime import datetime, timedelta, timezone
import sqlite3, secrets, os
from typing import Optional, Dict, Any

# === Cookies ===
SESSION_COOKIE = "pp_session"
CSRF_COOKIE    = "pp_csrf"

# Та же БД, что и в auth_manager
DB_PATH = "profitpal_auth.db"

# Админ из ENV (байпас для require_plan)
ADMIN_EMAIL = (os.getenv("ADMIN_EMAIL", "").strip().lower() or "")


def _db() -> sqlite3.Connection:
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
            """
            INSERT INTO user_sessions (user_id, session_token, expires_at, ip_address, user_agent, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
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
    Ставит pp_session и pp_csrf на правильный домен.
    Если хост *.profitpal.org → используем обобщённый .profitpal.org,
    чтобы кука была видна и apex, и сабдоменам.
    """
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
    # опционально для логов
    print(f"[auth] cookies set for host={request.url.hostname} domain={cookie_domain} secure={secure} token={token[:8]}...")


    def _fetch_user_by_session(token: str) -> Optional[Dict]:
        """Возвращает пользователя по токену сессии без обращения к зашифрованным полям.
           Планы/подписка — опционально (пытаемся прочитать, если колонка есть).
        """
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

                # Попробуем аккуратно получить статус оплаты, если колонка есть
                plan_type = None
                subscription_status = None
                try:
                    cols = {c[1] for c in con.execute("PRAGMA table_info(users)").fetchall()}
                    if "payment_status" in cols:
                        rps = con.execute("SELECT payment_status FROM users WHERE id = ?", (row["id"],)).fetchone()
                        if rps and rps[0] is not None:
                            ps = str(rps[0]).lower()
                            if ps in ("completed", "active", "paid", "lifetime"):
                                plan_type = "lifetime"
                                subscription_status = "active"
                            else:
                                subscription_status = "inactive"
                except sqlite3.OperationalError:
                    pass

                return {
                    "id": row["id"],
                    "is_active": row["is_active"],
                    "plan_type": plan_type,                 # None | "lifetime"
                    "subscription_status": subscription_status,  # None | "active" | "inactive"
                }
        except sqlite3.OperationalError as e:
            print(f"[security] session lookup error: {e}")
            return None

    # ⬇️ ДОБАВЬТЕ ЭТО (3 строки логики + возврат)
    email = (row["email"] or "").strip().lower()
    if ADMIN_EMAIL and email == ADMIN_EMAIL:
        return {
            "id": row["id"],
            "email": email,
            "license_key": row["license_key"],
            "is_active": 1,
            "plan_type": "lifetime",            # админ всегда как будто купил LIFETIME
            "subscription_status": "active"     # и подписка "активна"
        }


    # Нормализуем план/подписку
    plan_type: Optional[str] = None
    subscription_status: Optional[str] = None
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
        "plan_type": plan_type,                    # None | "lifetime"
        "subscription_status": subscription_status # None | "active" | "inactive"
    }


def _plan_rank(plan: Optional[str]) -> int:
    # lifetime — самый высокий
    order = {"lifetime": 3, "pro": 2, "standard": 1, "early_bird": 1}
    return order.get((plan or "").lower(), 0)


async def require_user(request: Request) -> Dict[str, Any]:
    """Пускаем только при валидной активной сессии (не даём 500)."""
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
    async def _dep(request: Request) -> Dict[str, Any]:
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
    # Headers у Starlette регистронезависимые; берём в нижнем регистре для ясности
    header = request.headers.get("x-csrf-token")
    cookie = request.cookies.get(CSRF_COOKIE)
    # Подсказка линтера: лучше сравнивать через is None
    if header is None or cookie is None or header != cookie:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
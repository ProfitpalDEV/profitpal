# migrate_security.py
import sqlite3

DB_PATH = "profitpal_auth.db"   # та же БД, что в security.py

REQUIRED_COLUMNS = {
    "user_id":        "INTEGER NOT NULL",
    "session_token":  "TEXT NOT NULL",
    "expires_at":     "TEXT",                    # не ставим NOT NULL, чтобы спокойно добавить
    "ip_address":     "TEXT",
    "user_agent":     "TEXT",
    "is_active":      "INTEGER NOT NULL DEFAULT 1",
}

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS user_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  session_token TEXT NOT NULL,
  expires_at TEXT,
  ip_address TEXT,
  user_agent TEXT,
  is_active INTEGER NOT NULL DEFAULT 1
);
"""

INDEXES = [
    ("idx_sessions_token",     "CREATE UNIQUE INDEX idx_sessions_token ON user_sessions(session_token)"),
    ("idx_sessions_user",      "CREATE INDEX idx_sessions_user ON user_sessions(user_id)"),
    # этот индекс создадим только если колонка is_active есть
    ("idx_sessions_active_exp","CREATE INDEX idx_sessions_active_exp ON user_sessions(is_active, expires_at)"),
]

def columns_in_table(con, table):
    cols = {}
    for r in con.execute(f"PRAGMA table_info({table})"):
        cols[r[1]] = r[2]  # name -> type
    return cols

def index_exists(con, name):
    row = con.execute("PRAGMA index_list('user_sessions')").fetchall()
    for _, idx_name, *_ in row:
        if idx_name == name:
            return True
    return False

def main():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row

    # 1) базовая таблица
    con.executescript(CREATE_TABLE_SQL)

    # 2) дотащить недостающие колонки
    existing = columns_in_table(con, "user_sessions")
    for col, decl in REQUIRED_COLUMNS.items():
        if col not in existing:
            # можно добавлять NOT NULL ТОЛЬКО с DEFAULT -> у нас так и сделано для is_active
            sql = f"ALTER TABLE user_sessions ADD COLUMN {col} {decl}"
            try:
                con.execute(sql)
                print(f"➕ Added column: {col}")
            except Exception as e:
                print(f"⚠️  Skipped column {col}: {e}")

    # 3) индексы
    # token
    if not index_exists(con, "idx_sessions_token"):
        con.execute(INDEXES[0][1])
    # user
    if not index_exists(con, "idx_sessions_user"):
        con.execute(INDEXES[1][1])
    # is_active, expires_at — только если колонка is_active реально есть
    existing = columns_in_table(con, "user_sessions")
    if "is_active" in existing and not index_exists(con, "idx_sessions_active_exp"):
        con.execute(INDEXES[2][1])

    con.commit()
    con.close()
    print("✅ user_sessions ready / migrated.")

if __name__ == "__main__":
    main()

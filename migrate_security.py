# migrate_security.py
import sqlite3

DB_PATH = "profitpal.db"  # <-- тот же путь, что в security.py

DDL = """
CREATE TABLE IF NOT EXISTS user_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  session_token TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  ip_address TEXT,
  user_agent TEXT,
  is_active INTEGER NOT NULL DEFAULT 1
);
"""

INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_token ON user_sessions(session_token)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_userid ON user_sessions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_active ON user_sessions(is_active, expires_at)"
]

def ensure_columns(con):
    cur = con.execute("PRAGMA table_info(user_sessions)")
    cols = {row[1] for row in cur.fetchall()}
    needed = {
        "id","user_id","session_token","expires_at","ip_address","user_agent","is_active"
    }
    missing = needed - cols
    for col in missing:
        if col == "ip_address":
            con.execute("ALTER TABLE user_sessions ADD COLUMN ip_address TEXT")
        elif col == "user_agent":
            con.execute("ALTER TABLE user_sessions ADD COLUMN user_agent TEXT")
        elif col == "is_active":
            con.execute("ALTER TABLE user_sessions ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        else:
            # если критично чего-то базового нет — можно пересоздать таблицу вручную
            pass

def main():
    con = sqlite3.connect(DB_PATH)
    con.executescript(DDL)
    ensure_columns(con)
    for sql in INDEXES:
        con.execute(sql)
    con.commit()
    con.close()
    print("✅ user_sessions ready")

if __name__ == "__main__":
    main()

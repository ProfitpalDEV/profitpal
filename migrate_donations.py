# migrate_donations.py
import sqlite3

DB_PATH = "profitpal.db"

DDL = """
CREATE TABLE IF NOT EXISTS donations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  amount_cents INTEGER NOT NULL,
  currency TEXT NOT NULL,
  donation_type TEXT,
  stripe_payment_intent_id TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

ALTS = [
    "ALTER TABLE users ADD COLUMN stripe_customer_id TEXT",
    "ALTER TABLE users ADD COLUMN stripe_default_pm TEXT",
]

IDX = [
    "CREATE INDEX IF NOT EXISTS idx_donations_userid ON donations(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_donations_created ON donations(created_at)",
]

def safe(con, sql):
    try: con.execute(sql)
    except: pass

def main():
    con = sqlite3.connect(DB_PATH)
    con.executescript(DDL)
    for sql in ALTS: safe(con, sql)
    for sql in IDX: con.execute(sql)
    con.commit(); con.close()
    print("✅ donations ready (and users columns ensured)")

if __name__ == "__main__":
    main()

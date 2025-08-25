import sqlite3
from datetime import datetime
import json

def init_db():
    conn = sqlite3.connect('profitpal.db')
    c = conn.cursor()

    # Таблица для Trading Journal
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        date DATE NOT NULL,
        type TEXT NOT NULL,
        symbol TEXT NOT NULL,
        action TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        price REAL NOT NULL,
        commission REAL DEFAULT 0,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    # Таблица для Watchlist
    c.execute('''CREATE TABLE IF NOT EXISTS watchlist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, symbol)
    )''')

    conn.commit()
    conn.close()

# Функции для Trading Journal
def add_transaction(user_id, data):
    conn = sqlite3.connect('profitpal.db')
    c = conn.cursor()
    c.execute('''INSERT INTO transactions 
                 (user_id, date, type, symbol, action, quantity, price, commission, notes)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (user_id, data['date'], data['type'], data['symbol'], 
               data['action'], data['quantity'], data['price'], 
               data['commission'], data.get('notes', '')))
    conn.commit()
    conn.close()
    return c.lastrowid

def get_transactions(user_id):
    conn = sqlite3.connect('profitpal.db')
    c = conn.cursor()
    c.execute('SELECT * FROM transactions WHERE user_id = ? ORDER BY date DESC', (user_id,))
    transactions = c.fetchall()
    conn.close()
    return transactions

def delete_transaction(user_id, transaction_id):
    conn = sqlite3.connect('profitpal.db')
    c = conn.cursor()
    c.execute('DELETE FROM transactions WHERE user_id = ? AND id = ?', (user_id, transaction_id))
    conn.commit()
    conn.close()
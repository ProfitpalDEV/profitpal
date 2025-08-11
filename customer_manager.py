# customer_manager.py - Отдельный модуль для управления клиентами

import json
import base64
import hashlib
from cryptography.fernet import Fernet
from datetime import datetime
import sqlite3
import smtplib
from email.mime.text import MimeText
from email.mime.multipart import MimeMultipart
import os
import asyncio
from typing import Optional, List, Dict

class CustomerManager:
    def __init__(self):
        # Генерируем ключ шифрования из environment variable
        secret = os.getenv('CUSTOMER_DB_SECRET', 'profitpal_denava_secret_key_2025')
        self.key = hashlib.sha256(secret.encode()).digest()
        self.fernet = Fernet(base64.urlsafe_b64encode(self.key))

        self.db_path = 'customers.db'
        self.init_database()

    def init_database(self):
        """Инициализация базы данных клиентов"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Таблица клиентов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                encrypted_email TEXT UNIQUE NOT NULL,
                encrypted_card_last4 TEXT,
                stripe_customer_id TEXT,
                signup_date TEXT,
                plan_type TEXT,
                original_setup_price REAL,
                current_monthly_price REAL,
                status TEXT DEFAULT 'active',
                last_notification TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Таблица уведомлений о ценах
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS price_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notification_date TEXT,
                old_price REAL,
                new_price REAL,
                customers_notified INTEGER,
                effective_date TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Таблица статистики
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS email_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_type TEXT,
                total_sent INTEGER,
                successful INTEGER,
                failed INTEGER,
                sent_date TEXT
            )
        ''')

        conn.commit()
        conn.close()
        print("✅ Customer database initialized")

    def encrypt_data(self, data: str) -> str:
        """Шифрование данных"""
        if not data:
            return None
        return self.fernet.encrypt(data.encode()).decode()

    def decrypt_data(self, encrypted_data: str) -> str:
        """Расшифровка данных"""
        if not encrypted_data:
            return None
        return self.fernet.decrypt(encrypted_data.encode()).decode()

    def add_customer(self, email: str, stripe_customer_id: str = None, 
                    card_last4: str = None, plan_type: str = "lifetime", 
                    setup_price: float = 24.99, monthly_price: float = 4.99):
        """Добавление нового клиента"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        encrypted_email = self.encrypt_data(email)
        encrypted_card = self.encrypt_data(card_last4) if card_last4 else None

        try:
            cursor.execute('''
                INSERT INTO customers 
                (encrypted_email, encrypted_card_last4, stripe_customer_id, 
                 signup_date, plan_type, original_setup_price, current_monthly_price, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (encrypted_email, encrypted_card, stripe_customer_id,
                  datetime.now().isoformat(), plan_type, setup_price, monthly_price, 'active'))

            conn.commit()
            print(f"✅ Customer added: {email}")
            return True

        except sqlite3.IntegrityError:
            print(f"⚠️  Customer already exists: {email}")
            return False
        finally:
            conn.close()

    def get_customer_by_email(self, email: str) -> Optional[Dict]:
        """Получение клиента по email"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Нужно проверить все записи, так как email зашифрован
        cursor.execute('SELECT * FROM customers WHERE status = "active"')

        for row in cursor.fetchall():
            try:
                decrypted_email = self.decrypt_data(row[1])
                if decrypted_email == email:
                    customer = {
                        'id': row[0],
                        'email': decrypted_email,
                        'card_last4': self.decrypt_data(row[2]) if row[2] else None,
                        'stripe_customer_id': row[3],
                        'signup_date': row[4],
                        'plan_type': row[5], 
                        'original_setup_price': row[6],
                        'current_monthly_price': row[7],
                        'status': row[8],
                        'last_notification': row[9]
                    }
                    conn.close()
                    return customer
            except:
                continue

        conn.close()
        return None

    def get_all_active_customers(self) -> List[Dict]:
        """Получение всех активных клиентов"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('SELECT * FROM customers WHERE status = "active"')
        customers = []

        for row in cursor.fetchall():
            try:
                customer = {
                    'id': row[0],
                    'email': self.decrypt_data(row[1]),
                    'card_last4': self.decrypt_data(row[2]) if row[2] else None,
                    'stripe_customer_id': row[3],
                    'signup_date': row[4],
                    'plan_type': row[5],
                    'original_setup_price': row[6],
                    'current_monthly_price': row[7],
                    'status': row[8],
                    'last_notification': row[9]
                }
                customers.append(customer)
            except Exception as e:
                print(f"⚠️  Error decrypting customer data: {e}")
                continue

        conn.close()
        return customers

    def get_customer_stats(self) -> Dict:
        """Получение статистики клиентов"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Общая статистика
        cursor.execute('SELECT COUNT(*) FROM customers WHERE status = "active"')
        total_active = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM customers')
        total_all = cursor.fetchone()[0]

        cursor.execute('SELECT plan_type, COUNT(*) FROM customers WHERE status = "active" GROUP BY plan_type')
        plan_stats = dict(cursor.fetchall())

        conn.close()

        return {
            'total_active': total_active,
            'total_all': total_all,
            'by_plan': plan_stats,
            'generated_at': datetime.now().isoformat()
        }

# Глобальный экземпляр менеджера клиентов
customer_manager = CustomerManager()

# Функции для простого использования в main.py
def add_new_customer(email: str, stripe_customer_id: str = None, card_last4: str = None):
    """Простая функция для добавления клиента из main.py"""
    return customer_manager.add_customer(email, stripe_customer_id, card_last4)

def get_customer_count() -> int:
    """Получение количества активных клиентов"""
    return len(customer_manager.get_all_active_customers())

def customer_exists(email: str) -> bool:
    """Проверка существования клиента"""
    return customer_manager.get_customer_by_email(email) is not None

# Инициализация при импорте модуля
if __name__ == "__main__":
    print("Customer Manager initialized")
    print(f"Active customers: {get_customer_count()}")
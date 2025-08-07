# auth_manager.py - Система аутентификации ProfitPal

import sqlite3
import hashlib
import secrets
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from cryptography.fernet import Fernet
import base64

class AuthManager:
    def __init__(self):
        # Ключ шифрования из environment variable
        secret = os.getenv('AUTH_SECRET_KEY', 'profitpal_auth_secret_2025_denava')
        self.key = hashlib.sha256(secret.encode()).digest()
        self.fernet = Fernet(base64.urlsafe_b64encode(self.key))

        self.db_path = 'profitpal_auth.db'
        self.init_database()
        print("✅ Auth Manager initialized")

    def init_database(self):
        """Инициализация базы данных аутентификации"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Таблица пользователей с зашифрованными данными
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                encrypted_email TEXT UNIQUE NOT NULL,
                encrypted_full_name TEXT NOT NULL,
                license_key TEXT UNIQUE NOT NULL,
                stripe_customer_id TEXT,
                payment_status TEXT DEFAULT 'completed',
                card_last4 TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP,
                login_count INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT 1
            )
        ''')

        # Таблица сессий для безопасности
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                session_token TEXT UNIQUE NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                ip_address TEXT,
                user_agent TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')

        # Таблица попыток входа (для безопасности)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS login_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT,
                license_key TEXT,
                success BOOLEAN,
                ip_address TEXT,
                user_agent TEXT,
                attempt_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()
        conn.close()
        print("✅ Auth database initialized")

    def encrypt_data(self, data: str) -> str:
        """Шифрование чувствительных данных"""
        if not data:
            return None
        return self.fernet.encrypt(data.encode()).decode()

    def decrypt_data(self, encrypted_data: str) -> str:
        """Расшифровка данных"""
        if not encrypted_data:
            return None
        try:
            return self.fernet.decrypt(encrypted_data.encode()).decode()
        except:
            return None

    def generate_license_key(self, email: str, full_name: str) -> str:
        """Генерация уникального лицензионного ключа"""
        # Создаем уникальный seed из email, имени и timestamp
        seed = f"{email.lower().strip()}_{full_name.upper().strip()}_{datetime.now().isoformat()}_{secrets.token_hex(16)}"

        # Генерируем hash
        hash_object = hashlib.sha256(seed.encode())
        hash_hex = hash_object.hexdigest()

        # Форматируем как PP-XXXX-XXXX-XXXX
        key_part = hash_hex[:12].upper()
        license_key = f"PP-{key_part[:4]}-{key_part[4:8]}-{key_part[8:12]}"

        return license_key

    def create_user(self, email: str, full_name: str, stripe_customer_id: str = None, 
                   card_last4: str = None) -> Dict[str, Any]:
        """Создание нового пользователя после успешной оплаты"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Проверяем, не существует ли уже пользователь с таким email
            existing_user = self.get_user_by_email(email)
            if existing_user:
                return {
                    "success": False,
                    "error": "User already exists",
                    "license_key": existing_user.get("license_key")
                }

            # Генерируем лицензионный ключ
            license_key = self.generate_license_key(email, full_name)

            # Шифруем чувствительные данные
            encrypted_email = self.encrypt_data(email.lower().strip())
            encrypted_name = self.encrypt_data(full_name.strip())

            # Сохраняем пользователя
            cursor.execute('''
                INSERT INTO users 
                (encrypted_email, encrypted_full_name, license_key, stripe_customer_id, 
                 card_last4, payment_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (encrypted_email, encrypted_name, license_key, stripe_customer_id,
                  card_last4, 'completed', datetime.now().isoformat()))

            user_id = cursor.lastrowid
            conn.commit()
            conn.close()

            print(f"✅ User created: {email} → {license_key}")

            return {
                "success": True,
                "user_id": user_id,
                "email": email,
                "full_name": full_name,
                "license_key": license_key,
                "message": "User created successfully"
            }

        except Exception as e:
            print(f"❌ Error creating user: {e}")
            return {
                "success": False,
                "error": f"Failed to create user: {str(e)}"
            }

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Получение пользователя по email (расшифровка всех записей)"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('SELECT * FROM users WHERE is_active = 1')

            for row in cursor.fetchall():
                try:
                    decrypted_email = self.decrypt_data(row[1])
                    if decrypted_email and decrypted_email.lower() == email.lower().strip():
                        user_data = {
                            'id': row[0],
                            'email': decrypted_email,
                            'full_name': self.decrypt_data(row[2]),
                            'license_key': row[3],
                            'stripe_customer_id': row[4],
                            'payment_status': row[5],
                            'card_last4': row[6],
                            'created_at': row[7],
                            'last_login': row[8],
                            'login_count': row[9],
                            'is_active': bool(row[10])
                        }
                        conn.close()
                        return user_data
                except:
                    continue

            conn.close()
            return None

        except Exception as e:
            print(f"❌ Error getting user by email: {e}")
            return None

    def validate_credentials(self, email: str, license_key: str) -> Dict[str, Any]:
        """🎯 ГЛАВНАЯ ФУНКЦИЯ: Проверка email + license и возврат имени для подсветки"""
        try:
            # Логируем попытку входа
            self.log_login_attempt(email, license_key, False)

            # Получаем пользователя по email
            user = self.get_user_by_email(email)

            if not user:
                return {
                    "valid": False,
                    "error": "User not found",
                    "show_name": False
                }

            # Проверяем license key
            if user['license_key'] != license_key.strip().upper():
                return {
                    "valid": False,
                    "error": "Invalid license key",
                    "show_name": False
                }

            # Проверяем статус оплаты
            if user['payment_status'] != 'completed':
                return {
                    "valid": False,
                    "error": "Payment not completed",
                    "show_name": False
                }

            # ✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ - ВОЗВРАЩАЕМ ИМЯ ДЛЯ ПОДСВЕТКИ
            self.log_login_attempt(email, license_key, True)

            return {
                "valid": True,
                "show_name": True,
                "full_name": user['full_name'],
                "email": user['email'],
                "license_key": user['license_key'],
                "user_id": user['id'],
                "last_login": user['last_login'],
                "login_count": user['login_count']
            }

        except Exception as e:
            print(f"❌ Error validating credentials: {e}")
            return {
                "valid": False,
                "error": "Validation failed",
                "show_name": False
            }

    def authenticate_user(self, email: str, license_key: str, full_name: str = None, 
                         ip_address: str = None, user_agent: str = None) -> Dict[str, Any]:
        """Полная аутентификация пользователя с созданием сессии"""
        try:
            # Сначала валидируем credentials
            validation = self.validate_credentials(email, license_key)

            if not validation['valid']:
                return validation

            # Если передано имя - проверяем его соответствие
            if full_name and full_name.strip() != validation['full_name']:
                return {
                    "authenticated": False,
                    "error": "Name mismatch"
                }

            # Обновляем данные последнего входа
            self.update_last_login(validation['user_id'])

            # Создаем сессию
            session_token = self.create_session(validation['user_id'], ip_address, user_agent)

            return {
                "authenticated": True,
                "session_token": session_token,
                "user": {
                    "id": validation['user_id'],
                    "email": validation['email'],
                    "full_name": validation['full_name'],
                    "license_key": validation['license_key']
                },
                "message": f"Welcome back, {validation['full_name']}!"
            }

        except Exception as e:
            print(f"❌ Authentication error: {e}")
            return {
                "authenticated": False,
                "error": "Authentication failed"
            }

    def create_session(self, user_id: int, ip_address: str = None, 
                      user_agent: str = None) -> str:
        """Создание пользовательской сессии"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Генерируем уникальный токен сессии
            session_token = secrets.token_urlsafe(32)
            expires_at = (datetime.now() + timedelta(days=30)).isoformat()

            # Сохраняем сессию
            cursor.execute('''
                INSERT INTO user_sessions 
                (user_id, session_token, expires_at, ip_address, user_agent)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, session_token, expires_at, ip_address, user_agent))

            conn.commit()
            conn.close()

            print(f"✅ Session created for user {user_id}")
            return session_token

        except Exception as e:
            print(f"❌ Error creating session: {e}")
            return None

    def validate_session(self, session_token: str) -> Optional[Dict[str, Any]]:
        """Проверка валидности сессии"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                SELECT s.*, u.encrypted_email, u.encrypted_full_name, u.license_key
                FROM user_sessions s
                JOIN users u ON s.user_id = u.id
                WHERE s.session_token = ? AND s.expires_at > ? AND u.is_active = 1
            ''', (session_token, datetime.now().isoformat()))

            row = cursor.fetchone()
            conn.close()

            if row:
                return {
                    'session_id': row[0],
                    'user_id': row[1],
                    'email': self.decrypt_data(row[6]),
                    'full_name': self.decrypt_data(row[7]),
                    'license_key': row[8],
                    'expires_at': row[3]
                }

            return None

        except Exception as e:
            print(f"❌ Error validating session: {e}")
            return None

    def update_last_login(self, user_id: int):
        """Обновление времени последнего входа"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                UPDATE users 
                SET last_login = ?, login_count = login_count + 1
                WHERE id = ?
            ''', (datetime.now().isoformat(), user_id))

            conn.commit()
            conn.close()

        except Exception as e:
            print(f"❌ Error updating last login: {e}")

    def log_login_attempt(self, email: str, license_key: str, success: bool, 
                         ip_address: str = None, user_agent: str = None):
        """Логирование попыток входа для безопасности"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO login_attempts 
                (email, license_key, success, ip_address, user_agent)
                VALUES (?, ?, ?, ?, ?)
            ''', (email, license_key[:8] + "...", success, ip_address, user_agent))

            conn.commit()
            conn.close()

        except Exception as e:
            print(f"❌ Error logging attempt: {e}")

    def get_user_stats(self) -> Dict[str, Any]:
        """Получение статистики пользователей"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Общая статистика
            cursor.execute('SELECT COUNT(*) FROM users WHERE is_active = 1')
            active_users = cursor.fetchone()[0]

            cursor.execute('SELECT COUNT(*) FROM users')
            total_users = cursor.fetchone()[0]

            cursor.execute('SELECT COUNT(*) FROM user_sessions WHERE expires_at > ?', 
                          (datetime.now().isoformat(),))
            active_sessions = cursor.fetchone()[0]

            cursor.execute('SELECT COUNT(*) FROM login_attempts WHERE success = 1 AND attempt_time > ?',
                          (datetime.now().replace(hour=0, minute=0, second=0).isoformat(),))
            today_logins = cursor.fetchone()[0]

            conn.close()

            return {
                "active_users": active_users,
                "total_users": total_users,
                "active_sessions": active_sessions,
                "today_logins": today_logins,
                "generated_at": datetime.now().isoformat()
            }

        except Exception as e:
            print(f"❌ Error getting stats: {e}")
            return {}

    def deactivate_user(self, email: str) -> bool:
        """Деактивация пользователя"""
        try:
            user = self.get_user_by_email(email)
            if not user:
                return False

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('UPDATE users SET is_active = 0 WHERE id = ?', (user['id'],))
            conn.commit()
            conn.close()

            print(f"✅ User deactivated: {email}")
            return True

        except Exception as e:
            print(f"❌ Error deactivating user: {e}")
            return False

# Глобальный экземпляр менеджера аутентификации
auth_manager = AuthManager()

# ==========================================
# ПРОСТЫЕ ФУНКЦИИ ДЛЯ ИСПОЛЬЗОВАНИЯ В MAIN.PY
# ==========================================

def create_new_user(email: str, full_name: str, stripe_customer_id: str = None, 
                   card_last4: str = None) -> Dict[str, Any]:
    """Создание пользователя после успешной оплаты"""
    return auth_manager.create_user(email, full_name, stripe_customer_id, card_last4)

def validate_user_credentials(email: str, license_key: str) -> Dict[str, Any]:
    """🎯 ГЛАВНАЯ ФУНКЦИЯ: Email + License → Name для подсветки"""
    return auth_manager.validate_credentials(email, license_key)

def authenticate_user_login(email: str, license_key: str, full_name: str = None,
                          ip_address: str = None, user_agent: str = None) -> Dict[str, Any]:
    """Полная аутентификация с созданием сессии"""
    return auth_manager.authenticate_user(email, license_key, full_name, ip_address, user_agent)

def check_session_validity(session_token: str) -> Optional[Dict[str, Any]]:
    """Проверка валидности сессии"""
    return auth_manager.validate_session(session_token)

def get_auth_stats() -> Dict[str, Any]:
    """Получение статистики аутентификации"""
    return auth_manager.get_user_stats()

# ==========================================
# ТЕСТИРОВАНИЕ И ИНИЦИАЛИЗАЦИЯ
# ==========================================

if __name__ == "__main__":
    print("\n🔐🔐🔐 AUTH MANAGER TESTING 🔐🔐🔐")

    # Тест создания пользователя
    test_result = create_new_user(
        email="vasja.pupkin@gmail.com",
        full_name="Vasja Pupkin",
        stripe_customer_id="cus_test123",
        card_last4="4242"
    )
    print(f"✅ Create user: {test_result}")

    if test_result["success"]:
        license_key = test_result["license_key"]

        # Тест валидации credentials
        validation = validate_user_credentials("vasja.pupkin@gmail.com", license_key)
        print(f"✅ Validation: {validation}")

        if validation["valid"]:
            # Тест полной аутентификации
            auth_result = authenticate_user_login(
                email="vasja.pupkin@gmail.com",
                license_key=license_key,
                full_name="Vasja Pupkin",
                ip_address="127.0.0.1"
            )
            print(f"✅ Authentication: {auth_result}")

    # Статистика
    stats = get_auth_stats()
    print(f"📊 Stats: {stats}")

    print("\n🎯 AUTH MANAGER READY FOR PRODUCTION! 🎯")

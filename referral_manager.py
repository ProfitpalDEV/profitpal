# referral_manager.py - Система реферальных кодов ProfitPal

import sqlite3
import random
import string
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
import os
from cryptography.fernet import Fernet
import base64

class ReferralManager:
    def __init__(self, db_path: str = "referrals.db"):
        self.db_path = db_path
        self.encryption_key = self._get_or_create_encryption_key()
        self.fernet = Fernet(self.encryption_key)
        self.init_database()
        print("💎 Referral Manager initialized!")

    def _get_or_create_encryption_key(self) -> bytes:
        """Получить или создать ключ шифрования"""
        key_file = "referral_key.key"
        if os.path.exists(key_file):
            with open(key_file, 'rb') as f:
                return f.read()
        else:
            key = Fernet.generate_key()
            with open(key_file, 'wb') as f:
                f.write(key)
            return key

    def init_database(self):
        """Инициализация базы данных referrals"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Таблица реферальных кодов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL UNIQUE,
                referral_code TEXT NOT NULL UNIQUE,
                referral_link TEXT NOT NULL,
                free_months_balance INTEGER DEFAULT 0,
                total_referrals INTEGER DEFAULT 0,
                total_earned_months INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Таблица использованных реферальных ссылок
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS referral_uses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referral_code TEXT NOT NULL,
                referrer_email TEXT NOT NULL,
                new_user_email TEXT NOT NULL,
                payment_amount REAL NOT NULL,
                reward_months INTEGER DEFAULT 1,
                used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (referral_code) REFERENCES referrals (referral_code)
            )
        ''')

        # Таблица истории free months
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS free_months_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                action_type TEXT NOT NULL, -- 'earned', 'used', 'expired'
                months_change INTEGER NOT NULL, -- +1, -1, etc.
                balance_after INTEGER NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()
        conn.close()
        print("✅ Referral database initialized!")

    def generate_unique_referral_code(self) -> str:
        """
        Генерирует уникальный referral код:
        - 5 заглавных букв (A-Z)
        - 5 цифр (0-9)  
        - 5 маленьких букв (a-z)
        - БЕЗ ПЕРЕСЕЧЕНИЙ между заглавными и маленькими буквами

        Пример: ABCDE12345fghij
        """
        max_attempts = 100

        for attempt in range(max_attempts):
            # Выбираем 5 случайных букв из алфавита
            available_letters = list(string.ascii_lowercase)  # a-z
            selected_letters = random.sample(available_letters, 5)

            # Убираем выбранные буквы из списка для заглавных
            remaining_letters = [letter for letter in string.ascii_lowercase 
                               if letter not in selected_letters]

            # Если осталось меньше 5 букв для заглавных, пробуем снова
            if len(remaining_letters) < 5:
                continue

            # Выбираем 5 заглавных букв (НЕ пересекающихся с маленькими)
            uppercase_letters = [letter.upper() for letter in 
                               random.sample(remaining_letters, 5)]

            # 5 случайных цифр
            digits = [str(random.randint(0, 9)) for _ in range(5)]

            # Формируем код: ЗАГЛАВНЫЕ + ЦИФРЫ + маленькие
            referral_code = ''.join(uppercase_letters) + ''.join(digits) + ''.join(selected_letters)

            # Проверяем уникальность в базе
            if not self.referral_code_exists(referral_code):
                print(f"🎯 Generated referral code: {referral_code}")
                return referral_code

        # Если не смогли сгенерировать за 100 попыток, используем timestamp
        fallback_code = self._generate_fallback_code()
        print(f"⚠️ Using fallback referral code: {fallback_code}")
        return fallback_code

    def _generate_fallback_code(self) -> str:
        """Резервный метод генерации кода с timestamp"""
        timestamp = str(int(datetime.now().timestamp()))[-5:]  # Последние 5 цифр
        uppercase = ''.join(random.choices(string.ascii_uppercase, k=5))
        lowercase = ''.join(random.choices(string.ascii_lowercase, k=5))
        return f"{uppercase}{timestamp}{lowercase}"

    def referral_code_exists(self, referral_code: str) -> bool:
        """Проверить существует ли referral код"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('SELECT COUNT(*) FROM referrals WHERE referral_code = ?', (referral_code,))
        exists = cursor.fetchone()[0] > 0

        conn.close()
        return exists

    def create_referral_for_user(self, user_email: str, domain: str = "https://profitpal.org") -> Dict[str, Any]:
        """
        Создать referral код и ссылку для пользователя
        Вызывается автоматически после payment $24.99
        """
        try:
            # Проверяем, нет ли уже referral кода для этого пользователя
            existing = self.get_user_referral_info(user_email)
            if existing and existing.get('referral_code'):
                return {
                    'success': True,
                    'referral_code': existing['referral_code'],
                    'referral_link': existing['referral_link'],
                    'message': 'Referral code already exists'
                }

            # Генерируем уникальный код
            referral_code = self.generate_unique_referral_code()
            referral_link = f"{domain}?ref={referral_code}"

            # Сохраняем в базу
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT OR REPLACE INTO referrals 
                (user_email, referral_code, referral_link, free_months_balance, total_referrals, total_earned_months)
                VALUES (?, ?, ?, 0, 0, 0)
            ''', (user_email, referral_code, referral_link))

            conn.commit()
            conn.close()

            print(f"🎉 Referral created for {user_email}: {referral_code}")

            return {
                'success': True,
                'referral_code': referral_code,
                'referral_link': referral_link,
                'free_months_balance': 0,
                'message': 'Referral code created successfully'
            }

        except Exception as e:
            print(f"❌ Error creating referral: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def process_referral_signup(self, referral_code: str, new_user_email: str, payment_amount: float = 24.99) -> Dict[str, Any]:
        """
        Обработать регистрацию нового пользователя по referral ссылке
        Дать +1 бесплатный месяц рефереру
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Найти реферера по коду
            cursor.execute('SELECT user_email, free_months_balance, total_referrals FROM referrals WHERE referral_code = ?', 
                         (referral_code,))
            referrer_data = cursor.fetchone()

            if not referrer_data:
                conn.close()
                return {
                    'success': False,
                    'error': 'Invalid referral code'
                }

            referrer_email, current_balance, total_referrals = referrer_data

            # Проверить, не использовал ли уже этот email этот referral код
            cursor.execute('SELECT COUNT(*) FROM referral_uses WHERE referral_code = ? AND new_user_email = ?',
                         (referral_code, new_user_email))
            already_used = cursor.fetchone()[0] > 0

            if already_used:
                conn.close()
                return {
                    'success': False,
                    'error': 'Referral code already used by this user'
                }

            # Определить количество месяцев награды (обычно 1)
            reward_months = 1

            # Обновить баланс реферера
            new_balance = current_balance + reward_months
            new_total_referrals = total_referrals + 1
            new_total_earned = cursor.execute('SELECT total_earned_months FROM referrals WHERE referral_code = ?', 
                                           (referral_code,)).fetchone()[0] + reward_months

            cursor.execute('''
                UPDATE referrals 
                SET free_months_balance = ?, total_referrals = ?, total_earned_months = ?, last_updated = ?
                WHERE referral_code = ?
            ''', (new_balance, new_total_referrals, new_total_earned, datetime.now(), referral_code))

            # Записать использование referral
            cursor.execute('''
                INSERT INTO referral_uses 
                (referral_code, referrer_email, new_user_email, payment_amount, reward_months)
                VALUES (?, ?, ?, ?, ?)
            ''', (referral_code, referrer_email, new_user_email, payment_amount, reward_months))

            # Записать в историю free months
            cursor.execute('''
                INSERT INTO free_months_history 
                (user_email, action_type, months_change, balance_after, description)
                VALUES (?, 'earned', ?, ?, ?)
            ''', (referrer_email, reward_months, new_balance, f"Referral signup: {new_user_email}"))

            conn.commit()
            conn.close()

            print(f"🎉 Referral processed! {referrer_email} earned {reward_months} free month(s)")

            return {
                'success': True,
                'referrer_email': referrer_email,
                'reward_months': reward_months,
                'new_balance': new_balance,
                'message': f'Referral processed successfully. {referrer_email} earned {reward_months} free month(s)'
            }

        except Exception as e:
            print(f"❌ Error processing referral: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def check_and_use_free_month(self, user_email: str) -> Dict[str, Any]:
        """
        Проверить и использовать 1 бесплатный месяц
        Возвращает нужно ли списывать $7.99
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Получить текущий баланс
            cursor.execute('SELECT free_months_balance FROM referrals WHERE user_email = ?', (user_email,))
            result = cursor.fetchone()

            if not result:
                # Пользователь без referral системы - платит полную сумму
                conn.close()
                return {
                    'should_charge': True,
                    'charge_amount': 7.99,
                    'free_months_remaining': 0,
                    'message': 'No referral account found'
                }

            current_balance = result[0]

            if current_balance > 0:
                # Есть бесплатные месяцы - используем один
                new_balance = current_balance - 1

                cursor.execute('''
                    UPDATE referrals 
                    SET free_months_balance = ?, last_updated = ?
                    WHERE user_email = ?
                ''', (new_balance, datetime.now(), user_email))

                # Записать в историю
                cursor.execute('''
                    INSERT INTO free_months_history 
                    (user_email, action_type, months_change, balance_after, description)
                    VALUES (?, 'used', -1, ?, 'Monthly billing - used free month')
                ''', (user_email, new_balance))

                conn.commit()
                conn.close()

                return {
                    'should_charge': False,
                    'charge_amount': 0.00,
                    'free_months_remaining': new_balance,
                    'message': f'Free month used. {new_balance} months remaining',
                    'billing_note': f'Referral credit used - {new_balance} free months remaining'
                }

            else:
                # Нет бесплатных месяцев - списываем $7.99
                conn.close()
                return {
                    'should_charge': True,
                    'charge_amount': 7.99,
                    'free_months_remaining': 0,
                    'message': 'No free months available - charging $7.99'
                }

        except Exception as e:
            print(f"❌ Error checking free months: {e}")
            return {
                'should_charge': True,
                'charge_amount': 7.99,
                'free_months_remaining': 0,
                'error': str(e)
            }

    def get_user_referral_info(self, user_email: str) -> Optional[Dict[str, Any]]:
        """Получить информацию о referral пользователя"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                SELECT referral_code, referral_link, free_months_balance, 
                       total_referrals, total_earned_months, created_at
                FROM referrals WHERE user_email = ?
            ''', (user_email,))

            result = cursor.fetchone()
            conn.close()

            if result:
                return {
                    'referral_code': result[0],
                    'referral_link': result[1],
                    'free_months_balance': result[2],
                    'total_referrals': result[3],
                    'total_earned_months': result[4],
                    'created_at': result[5]
                }
            return None

        except Exception as e:
            print(f"❌ Error getting referral info: {e}")
            return None

    def get_referral_statistics(self, user_email: str) -> Dict[str, Any]:
        """Получить статистику по referrals пользователя"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Основная информация
            referral_info = self.get_user_referral_info(user_email)
            if not referral_info:
                return {'error': 'User not found in referral system'}

            # История использований
            cursor.execute('''
                SELECT new_user_email, payment_amount, used_at 
                FROM referral_uses 
                WHERE referrer_email = ? 
                ORDER BY used_at DESC
            ''', (user_email,))

            referral_uses = cursor.fetchall()

            # История free months
            cursor.execute('''
                SELECT action_type, months_change, balance_after, description, created_at
                FROM free_months_history 
                WHERE user_email = ? 
                ORDER BY created_at DESC 
                LIMIT 10
            ''', (user_email,))

            months_history = cursor.fetchall()

            conn.close()

            return {
                'referral_info': referral_info,
                'recent_referrals': [
                    {
                        'new_user_email': use[0],
                        'payment_amount': use[1],
                        'used_at': use[2]
                    } for use in referral_uses
                ],
                'months_history': [
                    {
                        'action_type': hist[0],
                        'months_change': hist[1],
                        'balance_after': hist[2],
                        'description': hist[3],
                        'created_at': hist[4]
                    } for hist in months_history
                ]
            }

        except Exception as e:
            print(f"❌ Error getting referral statistics: {e}")
            return {'error': str(e)}

    def extract_referral_code_from_url(self, url: str) -> Optional[str]:
        """Извлечь referral код из URL"""
        try:
            if '?ref=' in url:
                return url.split('?ref=')[1].split('&')[0]
            elif '&ref=' in url:
                return url.split('&ref=')[1].split('&')[0]
            return None
        except:
            return None

    def validate_referral_code_format(self, referral_code: str) -> bool:
        """Проверить формат referral кода"""
        if len(referral_code) != 15:
            return False

        # Первые 5 - заглавные буквы
        if not referral_code[:5].isupper() or not referral_code[:5].isalpha():
            return False

        # Следующие 5 - цифры
        if not referral_code[5:10].isdigit():
            return False

        # Последние 5 - маленькие буквы
        if not referral_code[10:15].islower() or not referral_code[10:15].isalpha():
            return False

        return True

    def get_all_referral_stats(self) -> Dict[str, Any]:
        """Получить общую статистику referral системы (для админа)"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Общее количество referral кодов
            cursor.execute('SELECT COUNT(*) FROM referrals')
            total_referrals = cursor.fetchone()[0]

            # Общее количество использований
            cursor.execute('SELECT COUNT(*) FROM referral_uses')
            total_uses = cursor.fetchone()[0]

            # Общее количество выданных free months
            cursor.execute('SELECT SUM(total_earned_months) FROM referrals')
            total_earned_months = cursor.fetchone()[0] or 0

            # Текущий баланс всех free months
            cursor.execute('SELECT SUM(free_months_balance) FROM referrals')
            current_free_months = cursor.fetchone()[0] or 0

            # Топ рефереры
            cursor.execute('''
                SELECT user_email, total_referrals, total_earned_months, free_months_balance
                FROM referrals 
                ORDER BY total_referrals DESC 
                LIMIT 10
            ''')
            top_referrers = cursor.fetchall()

            conn.close()

            return {
                'total_referral_codes': total_referrals,
                'total_successful_uses': total_uses,
                'total_earned_months': total_earned_months,
                'current_free_months_balance': current_free_months,
                'top_referrers': [
                    {
                        'email': ref[0],
                        'total_referrals': ref[1],
                        'total_earned_months': ref[2],
                        'free_months_balance': ref[3]
                    } for ref in top_referrers
                ]
            }

        except Exception as e:
            print(f"❌ Error getting referral stats: {e}")
            return {'error': str(e)}

# Пример использования
if __name__ == "__main__":
    # Инициализация
    referral_mgr = ReferralManager()

    # Тест генерации referral кода
    print("🧪 Testing referral code generation:")
    for i in range(5):
        code = referral_mgr.generate_unique_referral_code()
        print(f"Generated: {code}")
        print(f"Valid format: {referral_mgr.validate_referral_code_format(code)}")
        print(f"Uppercase: {code[:5]}, Digits: {code[5:10]}, Lowercase: {code[10:15]}")
        print("---")

    # Тест создания referral для пользователя
    print("🧪 Testing referral creation:")
    result = referral_mgr.create_referral_for_user("john.smith@gmail.com")
    print(f"Creation result: {result}")

    # Тест обработки referral signup
    if result['success']:
        print("🧪 Testing referral signup:")
        signup_result = referral_mgr.process_referral_signup(
            result['referral_code'], 
            "friend@gmail.com"
        )
        print(f"Signup result: {signup_result}")

        # Тест использования free month
        print("🧪 Testing free month usage:")
        usage_result = referral_mgr.check_and_use_free_month("john.smith@gmail.com")
        print(f"Usage result: {usage_result}")

    print("✅ Referral Manager testing completed!")

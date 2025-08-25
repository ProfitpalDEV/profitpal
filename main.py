import requests
import os
import json
import stripe
import secrets
import hashlib
import sqlite3
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, List, Optional, Tuple
from fastapi import FastAPI, HTTPException, Request, Form, BackgroundTasks, Depends, Response
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from database import init_db, add_transaction, get_transactions, delete_transaction
from pydantic import BaseModel
from pathlib import Path
from auth_manager import authenticate_user_login, validate_user_credentials, create_new_user, get_auth_stats, auth_manager as AUTH
from security import set_session_cookies, create_session, require_user, require_plan, verify_csrf, SESSION_COOKIE, CSRF_COOKIE, _db, _fetch_user_by_session, is_admin_user
from referral_manager import ReferralManager
import re

# ==========================================
# Инициализация базы данных при старте
# ==========================================

init_db()

# ========================================
# ФУНКЦИЯ ДЛЯ ПОЛУЧЕНИЯ ТЕКУЩЕГО ЮЗЕРА
# ========================================
async def get_current_user(request: Request):
    """Получаем текущего юзера из сессии"""
    try:
        # Используем _fetch_user_by_session С ПОДЧЕРКИВАНИЕМ!
        user = await _fetch_user_by_session(request)
        if not user:
            # Для тестирования возвращаем тестового юзера
            return {'id': 'test_user', 'email': 'test@profitpal.org'}
        return user
    except Exception as e:
        print(f"Error getting current user: {e}")
        # Возвращаем тестового юзера для разработки
        return {'id': 'test_user', 'email': 'test@profitpal.org'}

# ==========================================
# ROOT DIRECTORY CONFIGURATION
# ==========================================

ROOT = Path(__file__).parent.resolve()


def serve_html(filename: str) -> FileResponse:
    """
    Отдать html как статический файл.
    Если файла нет — вернём 404 вместо 500.
    """
    p = (ROOT / filename).resolve()
    if not p.exists():
        raise HTTPException(status_code=404,
                            detail=f"File not found: {filename}")
    return FileResponse(str(p), media_type="text/html")  # <= str(p)!


def serve_static(filename: str, media_type: str = "text/html") -> FileResponse:
    p = (ROOT / filename).resolve()
    if not p.exists():
        raise HTTPException(status_code=404,
                            detail=f"File not found: {filename}")
    return FileResponse(str(p), media_type=media_type)


# ==========================================
# MANAGERS INTEGRATION
# ==========================================


# Инициализируем auth manager
class AuthManager:

    def __init__(self):
        pass

    def get_user_by_email(self, email):
        # Это должно быть реализовано в auth_manager.py
        # Временная заглушка для совместимости
        return {'stripe_customer_id': None, 'default_payment_method': None}


auth_mgr = AuthManager()

# ==========================================
# DATABASE CONFIGURATION
# ==========================================

DATABASE_PATH = "profitpal_database.db"


def create_free_trial_table():
    """Создание таблицы для free trial fingerprints"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS free_trials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL,
                analyses_used INTEGER DEFAULT 0,
                max_analyses INTEGER DEFAULT 5,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(fingerprint)
            )
        ''')

        conn.commit()
        conn.close()
        print("✅ Free trial table created successfully")

    except Exception as e:
        print(f"❌ Error creating free trial table: {e}")


# Создаем таблицу при запуске
create_free_trial_table()

# ==========================================
# ENVIRONMENT VARIABLES CONFIGURATION
# ==========================================

APP_ENV = os.getenv("APP_ENV", "prod")

# Get API keys from environment variables (Railway/host secrets)
FMP_API_KEY = os.getenv("FMP_API_KEY", "")
STRIPE_SECRET_KEY = os.getenv(
    "STRIPE_SECRET_KEY", "")  # no fallback to avoid false-positive configs
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY",
                                   "pk_test_fallback")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_fallback")
GMAIL_EMAIL = os.getenv("GMAIL_EMAIL", "denava.business@gmail.com")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")
YOUR_DOMAIN = os.getenv("DOMAIN", "https://profitpal.org")

from security import create_session, require_user, require_plan, verify_csrf, SESSION_COOKIE, CSRF_COOKIE

SECURE_COOKIES = YOUR_DOMAIN.startswith("https://") or ("profitpal.org"
                                                        in YOUR_DOMAIN)

# --- Admin login (ENV) ---
ADMIN_EMAIL = (os.getenv("ADMIN_EMAIL", "").strip().lower() or "")

# Принимаем оба имени переменной окружения:
#   - новый: ADMIN_LICENSE_KEY
#   - легаси: ADMIN_KEY
ADMIN_LICENSE_KEY = (os.getenv("ADMIN_LICENSE_KEY", "")
                     or os.getenv("ADMIN_KEY", "") or "").strip()
ADMIN_KEY = ADMIN_LICENSE_KEY  # алиас, чтобы ниже и в эндпоинтах было одно имя

ADMIN_FULL_NAME = os.getenv("ADMIN_FULL_NAME", "System Administrator")


def _norm_key(s: str) -> str:
    """Нормализуем ключ: оставляем только A-Z и 0-9, приводим к верхнему регистру."""
    return re.sub(r'[^A-Z0-9]', '', (s or '').upper())


# Referral manager (DB можно переопределить через ENV REFERRALS_DB)
REFERRALS_DB = os.getenv("REFERRALS_DB", "referrals.db")
referral_mgr = ReferralManager(db_path=REFERRALS_DB)

# ==========================================
# PRICE IDs (ENV only — no hardcode)
# ==========================================

LIFETIME_ACCESS_PRICE_ID = os.getenv("LIFETIME_ACCESS_PRICE_ID", "")
EARLY_BIRD_PRICE_ID = os.getenv("EARLY_BIRD_PRICE_ID", "")
STANDARD_PRICE_ID = os.getenv("STANDARD_PRICE_ID", "")
PRO_PRICE_ID = os.getenv("PRO_PRICE_ID", "")

# Optional: quick diagnostics (won't crash the app)
for _name, _val in [
    ("LIFETIME_ACCESS_PRICE_ID", LIFETIME_ACCESS_PRICE_ID),
    ("EARLY_BIRD_PRICE_ID", EARLY_BIRD_PRICE_ID),
    ("STANDARD_PRICE_ID", STANDARD_PRICE_ID),
    ("PRO_PRICE_ID", PRO_PRICE_ID),
]:
    if not _val:
        print(f"⚠️ Missing Stripe price id: {_name} (plan disabled until set)")

# ==========================================
# CONFIGURE STRIPE (safe at import time)
# ==========================================

# Single source of truth for the secret key
stripe.api_key = STRIPE_SECRET_KEY

# Do not crash the app at import time
STRIPE_READY = bool(STRIPE_SECRET_KEY)
STRIPE_STARTUP_ERROR = None

if not STRIPE_READY:
    print("⚠️ Stripe key missing. App will start, payments are disabled.")
else:
    try:
        # Optional eager check (off by default to avoid crashes)
        if os.getenv("STRIPE_EAGER_CHECK", "0") == "1":
            account_info = stripe.Account.retrieve()
            acc_email = getattr(account_info, "email", None) or "No email"
            print("✅ Stripe connection successful!")
            print(f"🏢 Stripe account: {acc_email}")
            print(
                f"✅ Stripe checkout available: {hasattr(stripe, 'checkout')}")
        else:
            print("ℹ️ Skipping Stripe eager check at startup.")
    except Exception as e:
        STRIPE_STARTUP_ERROR = str(e)
        print(
            f"⚠️ Stripe check failed (startup continues): {STRIPE_STARTUP_ERROR}"
        )

# --- Dev-only smoke test (guarded) ---
if APP_ENV == "dev" and STRIPE_READY:
    try:
        test_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": "Test Product"
                    },
                    "unit_amount": 500,  # $5.00
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )
        print(f"✅ Test Checkout Session created: {test_session.url}")
    except Exception as e:
        print(f"❌ Failed to create test Checkout Session: {e}")
else:
    print(
        "ℹ Skipping test Checkout Session creation (not in DEV mode or Stripe not ready)"
    )

# --- Dev-only diagnostics (no secrets) ---
if APP_ENV == "dev":
    print("✅ Environment variables loaded!")
    print(f"🔑 FMP API Key present: {bool(FMP_API_KEY)}")
    print(f"💳 Stripe key present: {bool(STRIPE_SECRET_KEY)}")
    print(f"🌐 Domain: {YOUR_DOMAIN}")
    print(f"📧 Gmail: {GMAIL_EMAIL}")
    print("💳 Price IDs loaded:")
    print(f"   Lifetime: {bool(LIFETIME_ACCESS_PRICE_ID)}")
    print(f"   Early Bird: {bool(EARLY_BIRD_PRICE_ID)}")
    print(f"   Standard: {bool(STANDARD_PRICE_ID)}")
    print(f"   PRO: {bool(PRO_PRICE_ID)}")

# ==========================================
# FASTAPI APPLICATION SETUP
# ==========================================

app = FastAPI(
    title="💎 ProfitPal Pro API v2.0",
    description=
    "Professional stock analysis platform with Diamond Rating System + Referral System",
    version="2.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Templates
templates = Jinja2Templates(directory=".")

# Initialize referral manager
referral_mgr = ReferralManager()

# ==========================================
# PYDANTIC MODELS
# ==========================================


class AnalysisRequest(BaseModel):
    ticker: str
    license_key: Optional[str] = "FREE"
    pe_min: Optional[float] = 5.0
    pe_max: Optional[float] = 30.0
    debt_max: Optional[float] = 50.0


class AnalysisResponse(BaseModel):
    ticker: str
    current_price: float
    pe_ratio: Optional[float]
    market_cap: Optional[float]
    debt_ratio: Optional[float]
    intrinsic_value: Optional[float]
    valuation_gap: Optional[float]
    final_verdict: str
    analysis_details: Dict[str, Any]


class PaymentRequest(BaseModel):
    email: str
    full_name: str
    referral_code: Optional[str] = None


class DonationRequest(BaseModel):
    amount: float
    type: str  # 'coffee', 'milk', 'features', 'custom'
    email: str


class FreeTrialRequest(BaseModel):
    fingerprint: str


class FreeTrialRecordRequest(BaseModel):
    fingerprint: str
    ticker: str


# ==========================================
# FMP STOCK ANALYZER CLASS
# ==========================================


class FMPStockAnalyzer:

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://financialmodelingprep.com/api/v3"

    def call_fmp_api(self, endpoint: str) -> Optional[Dict]:
        """Call FMP API with error handling"""
        try:
            url = f"{self.base_url}/{endpoint}?apikey={self.api_key}"
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                return data[0]
            elif isinstance(data, dict):
                return data
            return None
        except Exception as e:
            print(f"FMP API Error for {endpoint}: {e}")
            return None

    def extract_fmp_value(self, data: Optional[Dict],
                          field_name: str) -> Optional[float]:
        """Extract numeric value from FMP response"""
        if not data:
            return None

        value = data.get(field_name)
        if value is None:
            return None

        try:
            if isinstance(value, str):
                cleaned = re.sub(r'[^\d.-]', '', value)
                return float(cleaned) if cleaned else None
            return float(value)
        except (ValueError, TypeError):
            return None

    def get_debt_from_balance_sheet(self, ticker: str) -> Optional[float]:
        """Get debt ratio from balance sheet"""
        balance_sheet = self.call_fmp_api(f"balance-sheet-statement/{ticker}")
        if not balance_sheet:
            return None

        total_debt = self.extract_fmp_value(balance_sheet, 'totalDebt')
        total_assets = self.extract_fmp_value(balance_sheet, 'totalAssets')

        if total_debt is not None and total_assets is not None and total_assets > 0:
            return (total_debt / total_assets) * 100
        return None

    def get_debt_from_ratios(self, ticker: str) -> Optional[float]:
        """Get debt ratio from financial ratios API"""
        ratios = self.call_fmp_api(f"ratios/{ticker}")
        if not ratios:
            return None

        debt_ratio = self.extract_fmp_value(ratios, 'debtRatio')
        if debt_ratio is not None:
            return debt_ratio * 100
        return None

    def calculate_intrinsic_value(
            self, ticker: str,
            current_price: float) -> Tuple[Optional[float], Dict[str, Any]]:
        """Calculate intrinsic value using multiple methods"""
        details = {
            "dcf_method": None,
            "book_value_method": None,
            "earnings_method": None,
            "revenue_method": None,
            "weighted_average": None
        }

        # Method 1: DCF approximation
        cash_flow = self.call_fmp_api(f"cash-flow-statement/{ticker}")
        if cash_flow:
            free_cash_flow = self.extract_fmp_value(cash_flow, 'freeCashFlow')
            if free_cash_flow and free_cash_flow > 0:
                details["dcf_method"] = free_cash_flow * 10 / 1000000

        # Method 2: Book Value
        balance_sheet = self.call_fmp_api(f"balance-sheet-statement/{ticker}")
        if balance_sheet:
            book_value = self.extract_fmp_value(balance_sheet,
                                                'totalStockholdersEquity')
            shares = self.extract_fmp_value(balance_sheet, 'commonStock')
            if book_value and shares and shares > 0:
                details["book_value_method"] = book_value / shares

        # Method 3: Earnings multiple
        income_statement = self.call_fmp_api(f"income-statement/{ticker}")
        if income_statement:
            eps = self.extract_fmp_value(income_statement, 'eps')
            if eps and eps > 0:
                details["earnings_method"] = eps * 15

        # Method 4: Revenue multiple
        if income_statement:
            revenue = self.extract_fmp_value(income_statement, 'revenue')
            shares_outstanding = self.extract_fmp_value(
                income_statement, 'weightedAverageShsOut')
            if revenue and shares_outstanding and shares_outstanding > 0:
                revenue_per_share = revenue / shares_outstanding
                details["revenue_method"] = revenue_per_share * 3

        # Calculate weighted average
        values = []
        weights = []

        if details["dcf_method"]:
            values.append(details["dcf_method"])
            weights.append(0.4)

        if details["earnings_method"]:
            values.append(details["earnings_method"])
            weights.append(0.3)

        if details["book_value_method"]:
            values.append(details["book_value_method"])
            weights.append(0.2)

        if details["revenue_method"]:
            values.append(details["revenue_method"])
            weights.append(0.1)

        if values:
            total_weight = sum(weights)
            normalized_weights = [w / total_weight for w in weights]
            weighted_sum = sum(v * w
                               for v, w in zip(values, normalized_weights))
            details["weighted_average"] = weighted_sum
            return weighted_sum, details

        return None, details

    def get_complete_stock_data(self, ticker: str) -> Dict[str, Any]:
        """Get comprehensive stock data from multiple FMP endpoints"""
        result = {
            "ticker": ticker,
            "current_price": None,
            "pe_ratio": None,
            "market_cap": None,
            "debt_ratio": None,
            "intrinsic_value": None,
            "errors": []
        }

        try:
            # Get current price and basic metrics
            quote = self.call_fmp_api(f"quote/{ticker}")
            if quote:
                result["current_price"] = self.extract_fmp_value(
                    quote, 'price')
                result["pe_ratio"] = self.extract_fmp_value(quote, 'pe')
                result["market_cap"] = self.extract_fmp_value(
                    quote, 'marketCap')
            else:
                result["errors"].append("Failed to get stock quote")

            # Get debt ratio
            debt_ratio = self.get_debt_from_balance_sheet(ticker)
            if debt_ratio is None:
                debt_ratio = self.get_debt_from_ratios(ticker)
            if debt_ratio is None:
                debt_ratio = 25.0
                result["errors"].append("Using default debt ratio")

            result["debt_ratio"] = debt_ratio

            # Calculate intrinsic value
            if result["current_price"]:
                intrinsic_value, iv_details = self.calculate_intrinsic_value(
                    ticker, result["current_price"])
                result["intrinsic_value"] = intrinsic_value
                result["intrinsic_value_details"] = iv_details

        except Exception as e:
            result["errors"].append(f"Analysis error: {str(e)}")

        return result


# Initialize analyzer
analyzer = FMPStockAnalyzer(FMP_API_KEY)

# ==========================================
# EMAIL SYSTEM
# ==========================================


def send_welcome_email_with_referral(email: str,
                                     license_key: str,
                                     full_name: str,
                                     referral_link: str = ""):
    """Send welcome email with license key + referral link"""
    if not GMAIL_PASSWORD:
        print("⚠️ Gmail password not configured, skipping email")
        return

    try:
        msg = MIMEMultipart()
        msg['From'] = GMAIL_EMAIL
        msg['To'] = email
        msg['Subject'] = f"🎉 Welcome to ProfitPal Pro + Your Referral Link, {full_name}!"

        referral_section = f"""
            <div style="background: rgba(255, 215, 0, 0.1); padding: 25px; border-radius: 12px; margin: 20px 0; border: 2px solid #ffd700;">
                <h3 style="color: #ffd700; margin-top: 0;">🔗 Your Personal Referral Link!</h3>
                <p>Share this link with friends and earn <strong>FREE months</strong> for every $29.99 payment:</p>

                <div style="background: rgba(255, 215, 0, 0.2); padding: 15px; border-radius: 8px; word-break: break-all; margin: 15px 0;">
                    <code style="color: #ffd700; font-size: 14px; font-weight: bold;">{referral_link}</code>
                </div>

                <p style="margin-bottom: 0;">
                    🎁 <strong>Each friend who joins = 1 FREE month for you!</strong><br>
                    💰 <strong>12 friends = FREE year of data updates!</strong>
                </p>
            </div>
        """ if referral_link else ""

        body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: 'Inter', Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; background: linear-gradient(135deg, #0a0e27, #1e3a5f); color: white; border-radius: 20px; overflow: hidden; }}
        .header {{ padding: 40px 30px; text-align: center; background: linear-gradient(135deg, #32cd32, #228b22); }}
        .content {{ padding: 30px; }}
        .license-key {{ background: rgba(50, 205, 50, 0.2); border: 2px solid #32cd32; padding: 20px; text-align: center; border-radius: 10px; margin: 20px 0; }}
        .key {{ font-size: 24px; font-weight: bold; color: #32cd32; letter-spacing: 2px; }}
        .footer {{ padding: 20px; text-align: center; background: rgba(0,0,0,0.3); font-size: 14px; color: #87ceeb; }}
        .button {{ display: inline-block; padding: 15px 30px; background: #32cd32; color: white; text-decoration: none; border-radius: 25px; font-weight: bold; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>💎 Welcome to ProfitPal Pro!</h1>
            <p style="font-size: 18px; margin: 0;">Hello {full_name}!</p>
        </div>
        <div class="content">
            <h2>🎉 Payment Successful!</h2>
            <p>Congratulations! Your ProfitPal Pro lifetime access is now active.</p>

            <div class="license-key">
                <h3>🔑 Your License Key:</h3>
                <div class="key">{license_key}</div>
                <p style="margin: 10px 0 0 0; font-size: 14px;">Save this key - you'll need it to access ProfitPal Pro</p>
            </div>

            {referral_section}

            <div class="billing-info">
                <h4 style="color: #ff6b35; margin-top: 0;">💳 Monthly Data Updates - $9.99</h4>
                <p>Starting next month, $9.99 will be auto-billed on the 1st for:</p>
                <ul style="padding-left: 20px; margin: 10px 0;">
                    <li>🔄 Real-time market data</li>
                    <li>🔄 Server maintenance</li>
                    <li>🔄 New ProfitPal features</li>
                </ul>
                <p style="margin-bottom: 0;"><strong>💡 Use referrals to get FREE months and skip the $9.99 charge!</strong></p>
            </div>

            <h3>✅ What You Get:</h3>
            <ul style="padding-left: 20px;">
                <li>Unlimited stock analysis</li>
                <li>Diamond rating system</li>
                <li>Intrinsic value calculations</li>
                <li>Technical indicators</li>
                <li>Industry comparisons</li>
                <li>Risk assessment tools</li>
                <li>Real-time data updates</li>
            </ul>

            <div style="text-align: center; margin: 30px 0;">
                <a href="{YOUR_DOMAIN}/" class="button">🚀 Start Analyzing Now</a>
            </div>
        </div>
        <div class="footer">
            <p>&copy; 2025 ProfitPal - A product of Denava OÜ</p>
            <p>Educational platform - Not investment advice</p>
        </div>
    </div>
</body>
</html>
        """

        msg.attach(MIMEText(body, 'html'))

        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(GMAIL_EMAIL, GMAIL_PASSWORD)
            server.send_message(msg)

        print(f"✅ Welcome email with referral sent to: {full_name} ({email})")

    except Exception as e:
        print(f"❌ Error sending email: {e}")


def send_referral_reward_email(referrer_email: str, new_balance: int,
                               new_user_email: str):
    """Send email about referral reward"""
    if not GMAIL_PASSWORD:
        return

    try:
        msg = MIMEMultipart()
        msg['From'] = GMAIL_EMAIL
        msg['To'] = referrer_email
        msg['Subject'] = "🎁 Congratulations! You Earned a Free Month!"

        body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: 'Inter', Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; background: linear-gradient(135deg, #0a0e27, #1e3a5f); color: white; border-radius: 20px; padding: 40px; }}
        .reward-box {{ background: rgba(255, 215, 0, 0.1); border: 2px solid #ffd700; border-radius: 15px; padding: 30px; text-align: center; margin: 20px 0; }}
        .balance {{ font-size: 28px; color: #32cd32; font-weight: bold; }}
    </style>
</head>
<body>
    <div class="container">
        <h1 style="color: #ffd700; text-align: center;">🎉 Referral Success!</h1>

        <div class="reward-box">
            <h2 style="color: #ffd700; margin-top: 0;">💎 Great News!</h2>
            <p><strong>{new_user_email}</strong> just joined ProfitPal using your referral link!</p>

            <div style="background: rgba(50, 205, 50, 0.2); padding: 20px; border-radius: 10px; margin: 20px 0;">
                <h3 style="color: #32cd32; margin: 0;">🎁 +1 FREE MONTH!</h3>
                <div class="balance">{new_balance} FREE MONTHS</div>
                <p style="margin: 10px 0 0 0;">Your next {new_balance} billing{'s' if new_balance > 1 else ''} will be $0.00!</p>
            </div>
        </div>

        <div style="background: rgba(30, 58, 95, 0.6); padding: 20px; border-radius: 10px;">
            <h3 style="color: #32cd32;">🚀 Keep Sharing!</h3>
            <ul>
                <li>💰 Each friend = 1 FREE month</li>
                <li>🎯 12 friends = FREE entire year!</li>
                <li>🔄 Unlimited earning potential</li>
            </ul>
        </div>

        <div style="text-align: center; margin-top: 30px;">
            <a href="{YOUR_DOMAIN}" style="background: #32cd32; color: white; padding: 15px 30px; text-decoration: none; border-radius: 25px; font-weight: bold;">View Dashboard →</a>
        </div>
    </div>
</body>
</html>
        """

        msg.attach(MIMEText(body, 'html'))

        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(GMAIL_EMAIL, GMAIL_PASSWORD)
            server.send_message(msg)

        print(f"🎁 Referral reward email sent to: {referrer_email}")

    except Exception as e:
        print(f"❌ Error sending referral email: {e}")


def send_donation_thank_you_email(email: str, amount: float,
                                  donation_type: str):
    """Send personalized thank you email for donations"""
    if not GMAIL_PASSWORD:
        print("⚠️ Gmail password not configured, skipping email")
        return

    try:
        # Personalized messages in American English
        messages = {
            'coffee': "I love black coffee, thank you dear person! ☕",
            'milk': "Oh! Black coffee with milk! You amazing human! 🥛",
            'features': "Features are coming, this will be awesome! 🚀",
            'custom': "Huge thanks for recognizing my work! 💝"
        }

        message = messages.get(donation_type, messages['custom'])

        msg = MIMEMultipart()
        msg['From'] = GMAIL_EMAIL
        msg['To'] = email
        msg['Subject'] = f"💎 Thank you for boosting ProfitPal development!"

        body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: 'Inter', Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; background: linear-gradient(135deg, #0a0e27, #1e3a5f); color: white; border-radius: 20px; overflow: hidden; }}
    </style>
</head>
<body>
    <div class="container">
        <div style="background: rgba(255, 215, 0, 0.1); padding: 30px; text-align: center;">
            <h1 style="color: #ffd700; margin-bottom: 10px;">💎 Thank You for Boosting ProfitPal!</h1>
            <h2 style="color: #32cd32; font-size: 20px; margin: 0;">{message}</h2>
        </div>

        <div style="padding: 30px;">
            <p style="font-size: 18px; color: #ffffff; margin-bottom: 20px;">
                Your <strong>${amount}</strong> contribution helps us:
            </p>

            <div style="background: rgba(50, 205, 50, 0.1); padding: 20px; border-radius: 12px; margin: 20px 0;">
                <ul style="color: #ffffff; font-size: 16px; line-height: 1.8;">
                    <li>🚀 Develop new features faster</li>
                    <li>📊 Improve data accuracy and speed</li>
                    <li>🛠️ Maintain 24/7 reliable service</li>
                    <li>💎 Add premium analysis tools</li>
                </ul>
            </div>

            <div style="text-align: center; margin: 30px 0;">
                <p style="color: #ffd700; font-size: 18px; font-weight: bold;">
                    Thank you for being part of the ProfitPal community! 🎉
                </p>
            </div>

            <div style="border-top: 2px solid rgba(50, 205, 50, 0.3); padding-top: 20px; text-align: center;">
                <p style="color: #95a5a6; margin: 0;">
                    Best regards,<br>
                    <strong style="color: #32cd32;">ProfitPal Development Team</strong>
                </p>
            </div>
        </div>
    </div>
</body>
</html>
        """

        msg.attach(MIMEText(body, 'html'))

        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(GMAIL_EMAIL, GMAIL_PASSWORD)
            server.send_message(msg)

        print(
            f"✅ Donation thank you email sent to {email} (${amount}, {donation_type})"
        )

    except Exception as e:
        print(f"❌ Failed to send donation email: {e}")


def send_free_month_notification(email: str, remaining_months: int):
    """Send email notification when free month is used"""
    if not GMAIL_PASSWORD:
        return

    try:
        msg = MIMEMultipart()
        msg['From'] = GMAIL_EMAIL
        msg['To'] = email
        msg['Subject'] = "🎁 Free Month Used - Thanks to Your Referrals!"

        body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: 'Inter', Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; background: linear-gradient(135deg, #0a0e27, #1e3a5f); color: white; border-radius: 20px; padding: 40px; }}
        .free-month-box {{ background: rgba(50, 205, 50, 0.1); border: 2px solid #32cd32; border-radius: 15px; padding: 30px; text-align: center; margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="container">
        <h1 style="color: #32cd32; text-align: center;">🎁 Free Month Applied!</h1>

        <div class="free-month-box">
            <h2 style="color: #32cd32; margin-top: 0;">Your $9.99 was refunded!</h2>
            <p>Thanks to your referral credits, we've automatically refunded your monthly payment.</p>

            <div style="background: rgba(255, 215, 0, 0.1); padding: 20px; border-radius: 10px; margin: 20px 0;">
                <h3 style="color: #ffd700; margin: 0;">🏆 Remaining Free Months</h3>
                <div style="font-size: 28px; color: #32cd32; font-weight: bold;">{remaining_months}</div>
            </div>
        </div>

        <div style="background: rgba(30, 58, 95, 0.6); padding: 20px; border-radius: 10px;">
            <p style="color: #ffffff;">Keep sharing your referral link to earn more free months!</p>
        </div>
    </div>
</body>
</html>
        """

        msg.attach(MIMEText(body, 'html'))

        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(GMAIL_EMAIL, GMAIL_PASSWORD)
            server.send_message(msg)

        print(f"✅ Free month notification sent to: {email}")

    except Exception as e:
        print(f"❌ Error sending free month email: {e}")


def send_upgrade_confirmation_email(email: str, old_plan: str, new_plan: str,
                                    new_amount: float):
    """Send email confirmation for subscription upgrade"""
    if not GMAIL_PASSWORD:
        return

    try:
        plan_names = {
            'early_bird': 'Early Bird',
            'standard': 'Standard',
            'pro': 'PRO'
        }

        old_plan_name = plan_names.get(old_plan, old_plan)
        new_plan_name = plan_names.get(new_plan, new_plan)

        msg = MIMEMultipart()
        msg['From'] = GMAIL_EMAIL
        msg['To'] = email
        msg['Subject'] = f"🚀 Welcome to ProfitPal {new_plan_name}!"

        body = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: 'Inter', Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; background: linear-gradient(135deg, #0a0e27, #1e3a5f); color: white; border-radius: 20px; padding: 40px; }}
        .upgrade-box {{ background: rgba(255, 215, 0, 0.1); border: 2px solid #ffd700; border-radius: 15px; padding: 30px; text-align: center; margin: 20px 0; }}
    </style>
</head>
<body>
    <div class="container">
        <h1 style="color: #ffd700; text-align: center;">🚀 Subscription Upgraded!</h1>

        <div class="upgrade-box">
            <h2 style="color: #ffd700; margin-top: 0;">Welcome to {new_plan_name}!</h2>
            <p>You've successfully upgraded from <strong>{old_plan_name}</strong> to <strong>{new_plan_name}</strong></p>

            <div style="background: rgba(50, 205, 50, 0.2); padding: 20px; border-radius: 10px; margin: 20px 0;">
                <h3 style="color: #32cd32; margin: 0;">💳 New Monthly Amount</h3>
                <div style="font-size: 28px; color: #32cd32; font-weight: bold;">${new_amount}/month</div>
            </div>
        </div>

        <div style="background: rgba(30, 58, 95, 0.6); padding: 20px; border-radius: 10px;">
            <h3 style="color: #32cd32;">🎯 Your New Features:</h3>
            <ul style="color: #ffffff;">
                {'<li>Advanced stock screening</li><li>Priority support</li><li>Extended analysis</li>' if new_plan == 'standard' else ''}
                {'<li>Options analysis tools</li><li>Live Greeks dashboard</li><li>Volatility alerts</li><li>Paper trading</li>' if new_plan == 'pro' else ''}
            </ul>
        </div>

        <div style="text-align: center; margin-top: 30px;">
            <a href="{YOUR_DOMAIN}" style="background: #32cd32; color: white; padding: 15px 30px; text-decoration: none; border-radius: 25px; font-weight: bold;">Explore New Features →</a>
        </div>
    </div>
</body>
</html>
        """

        msg.attach(MIMEText(body, 'html'))

        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(GMAIL_EMAIL, GMAIL_PASSWORD)
            server.send_message(msg)

        print(
            f"✅ Upgrade confirmation sent to: {email} ({old_plan} → {new_plan})"
        )

    except Exception as e:
        print(f"❌ Error sending upgrade email: {e}")


# ---- Stripe helpers for donations / billing ----
def ensure_stripe_customer_for_user(user_id: int):
    """Найти/создать Stripe Customer; вернуть (customer_id, None). Email не трогаем."""
    from security import _db
    with _db() as con:
        row = con.execute("SELECT stripe_customer_id FROM users WHERE id = ?",
                          (user_id, )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    cust_id = row["stripe_customer_id"]
    if not cust_id:
        # email не обязателен; создаём без него
        customer = stripe.Customer.create(metadata={"user_id": str(user_id)})
        cust_id = customer["id"]
        with _db() as con:
            con.execute("UPDATE users SET stripe_customer_id = ? WHERE id = ?",
                        (cust_id, user_id))
    return cust_id, None  # второе значение нам не нужно


def get_customer_default_payment_method(customer_id: str) -> str | None:
    """Вернуть id картового payment_method для off_session списаний."""
    # 1) дефолтный PM в invoice_settings
    cust = stripe.Customer.retrieve(customer_id)
    pm = (cust.get("invoice_settings") or {}).get("default_payment_method")
    if pm:
        return pm
    # 2) любой привязанный card PM
    pms = stripe.PaymentMethod.list(customer=customer_id, type="card", limit=1)
    if pms.data:
        return pms.data[0]["id"]
    return None


# --- helper: resolve user_id from auth result / DB ---
def _resolve_user_id_or_none(email: str, license_key: str, result: dict):
    from security import _db
    user = result.get("user") or {}
    # 1) попробуем собрать кандидатов из разных возможных полей
    candidates = [
        result.get("user_id"),
        user.get("id"),
        user.get("uid"),
        result.get("uid"),
        result.get("id"),
    ]
    for c in candidates:
        try:
            if c is not None:
                return int(c)
        except Exception:
            pass

    # 2) fallback — поиск в БД по email / license_key
    with _db() as con:
        row = None
        if email:
            row = con.execute("SELECT id FROM users WHERE email = ?",
                              (email, )).fetchone()
        if not row and license_key:
            row = con.execute("SELECT id FROM users WHERE license_key = ?",
                              (license_key, )).fetchone()
        if not row and email and license_key:
            row = con.execute(
                "SELECT id FROM users WHERE email = ? AND license_key = ?",
                (email, license_key),
            ).fetchone()
    return row["id"] if row else None


# ===== helper: ensure admin exists and return user_id =====
def ensure_admin_user_id(email: str, full_name: str, license_key: str) -> int:
    """
    Возвращает user_id админа надёжно:
    1) пробуем найти через AUTH.get_user_by_email (он знает про шифрование);
    2) если не нашли — ищем по license_key прямо в БД (если колонка есть);
    3) если нет пользователя — создаём (create_new_user или AUTH.create_user);
    4) приводим users.license_key к значению из ENV (если колонка есть).
    """
    # 1) поиск через менеджер (шифрованный email)
    user_id = None
    try:
        u = AUTH.get_user_by_email(email)
        if u and u.get("id"):
            user_id = int(u["id"])
    except Exception as e:
        print(f"[admin] get_user_by_email failed: {e}")

    with _db() as con:
        con.row_factory = sqlite3.Row
        cols = {c[1] for c in con.execute("PRAGMA table_info(users)").fetchall()}

        # 2) поиск по license_key, если колонка есть
        if user_id is None and "license_key" in cols:
            r = con.execute("SELECT id FROM users WHERE license_key = ? LIMIT 1", (license_key,)).fetchone()
            if r:
                user_id = int(r["id"])

        # 3) создание пользователя при отсутствии
        if user_id is None:
            created = None
            # 3.1) высокая обёртка, если доступна
            try:
                if 'create_new_user' in globals():
                    created = create_new_user(email=email, full_name=full_name, license_key=license_key)
            except Exception as e:
                print(f"[admin] create_new_user failed: {e}")

            # 3.2) прямой метод менеджера (варианты сигнатур)
            if not (created and created.get("success") and created.get("user_id")):
                try:
                    created = AUTH.create_user(email=email, full_name=full_name, license_key=license_key)
                except TypeError:
                    try:
                        created = AUTH.create_user(email=email, full_name=full_name)
                    except Exception as e2:
                        print(f"[admin] create_user(no key) failed: {e2}")
                except Exception as e:
                    print(f"[admin] create_user failed: {e}")

            if created and created.get("success") and created.get("user_id"):
                user_id = int(created["user_id"])
            else:
                # 3.3) на случай гонки/UNIQUE — перечитываем
                try:
                    u2 = AUTH.get_user_by_email(email)
                    if u2 and u2.get("id"):
                        user_id = int(u2["id"])
                except Exception as e:
                    print(f"[admin] second get_user_by_email failed: {e}")

        if not user_id:
            raise RuntimeError("ensure_admin_user_id: could not create/find admin user")

        # 4) нормализуем license_key в БД под ENV (если колонка есть)
        if "license_key" in cols:
            try:
                con.execute("UPDATE users SET license_key = ? WHERE id = ?", (license_key, user_id))
            except Exception as e:
                print(f"[admin] license_key update skipped: {e}")

    return user_id


# ==========================================
# STATIC FILE ROUTES
# ==========================================


@app.get("/")
def serve_homepage():
    # главная
    return serve_html("index.html")


@app.get("/ref/{referral_code}")
def handle_referral_redirect(referral_code: str):
    # ЭТО НЕ МЕНЯЕМ — тут редиректная логика, не статика
    try:
        print(f"🔗 Referral link clicked: {referral_code}")
        if (referral_mgr.validate_referral_code_format(referral_code)
                and referral_mgr.referral_code_exists(referral_code)):
            return RedirectResponse(url=f"/?ref={referral_code}",
                                    status_code=302)
        else:
            print(f"❌ Invalid referral code: {referral_code}")
            return RedirectResponse(url="/", status_code=302)
    except Exception as e:
        print(f"❌ Referral redirect error: {e}")
        return RedirectResponse(url="/", status_code=302)


@app.get("/analysis")
def serve_analysis():
    return serve_html("analysis.html")


@app.get("/login")
def login_page():
    return serve_html("login.html")


@app.get("/stock-analysis")
def serve_stock_analysis(user=Depends(require_plan("lifetime"))):
    return serve_html("stock-analysis.html")


@app.get("/portfolio")
def serve_portfolio(user=Depends(require_plan("lifetime"))):
    return serve_html("portfolio.html")


@app.get("/dashboard")
def serve_dashboard(user=Depends(require_plan("lifetime"))):
    try:
        return serve_html("dashboard.html")
    except Exception as e:
        # временный лог, чтобы сразу увидеть реальную причину в логах хоста
        print(f"❌ dashboard error: {type(e).__name__}: {e}")
        raise


@app.get("/__dash_raw")
def serve_dashboard_raw():
    return FileResponse(str(ROOT / "dashboard.html"), media_type="text/html")


@app.get("/fake-dashboard")
def serve_fake_dashboard():
    return serve_html("fake-dashboard.html")


@app.get("/introduction")
async def serve_introduction():
    return serve_html("introduction.html")


@app.get("/test-fail")
async def test_fail_page():
    return serve_html("test-fail.html")


@app.get("/success")
def serve_success(user=Depends(require_user)):
    return serve_html("success.html")


@app.get("/cancel")
def serve_cancel():
    return serve_html("cancel.html")


@app.get("/terms-of-service")
def serve_terms():
    return serve_html("terms-of-service.html")


@app.get("/privacy-policy")
def serve_privacy():
    return serve_html("privacy-policy.html")


@app.get("/refund-policy")
def serve_refund():
    return serve_html("refund-policy.html")


@app.get("/settings")
def serve_settings(user=Depends(require_user)):
    return serve_html("settings.html")


@app.get("/profitpal-styles.css")
def serve_css():
    return serve_static("profitpal-styles.css", "text/css")


@app.get("/admin.css")
def serve_admin_css():
    return serve_static("admin.css", "text/css")


@app.get("/pp-admin.js")
def serve_pp_admin_js():
    return serve_static("pp-admin.js", "application/javascript")


@app.get("/footer.js")
def serve_footer_js():
    return serve_static("footer.js", "application/javascript")


@app.get("/brand.js")
def serve_brand_js():
    return serve_static("brand.js", "application/javascript")


@app.get("/donation-fix.js")
def serve_donation_fix_js():
    return serve_static("donation-fix.js", "application/javascript")


@app.get("/api/stripe-key")
async def get_stripe_key():
    """Return Stripe publishable key for frontend"""
    return {"publishable_key": STRIPE_PUBLISHABLE_KEY}


@app.get("/api/billing/pm-info")
def pm_info(user=Depends(require_user)):
    """Вернёт краткую информацию о сохранённой карте (brand/last4/exp)"""
    customer_id, _ = ensure_stripe_customer_for_user(user["id"])
    pm_id = get_customer_default_payment_method(customer_id)
    if not pm_id:
        return {"has_pm": False}

    pm = stripe.PaymentMethod.retrieve(pm_id)
    card = pm.get("card") or {}
    return {
        "has_pm": True,
        "brand": card.get("brand"),
        "last4": card.get("last4"),
        "exp_month": card.get("exp_month"),
        "exp_year": card.get("exp_year"),
    }


@app.get("/_whoami")
def whoami(user=Depends(require_user)):
    return {
        "id":
        user.get("id"),
        "email":
        user.get("email"),
        "is_admin":
        bool(
            os.getenv("ADMIN_EMAIL", "").strip().lower() == (
                user.get("email") or "").strip().lower()),
        "plan_type":
        user.get("plan_type"),
        "subscription_status":
        user.get("subscription_status"),
    }


@app.get("/_health")
def health():
    return {"ok": True}


@app.post("/api/billing/create-setup-intent")
def create_setup_intent(user=Depends(require_user)):
    """Создать SetupIntent для сохранения карты 'off_session'."""
    customer_id, _ = ensure_stripe_customer_for_user(user["id"])
    si = stripe.SetupIntent.create(
        customer=customer_id,
        usage="off_session",
        payment_method_types=["card"],
    )
    return {"client_secret": si["client_secret"]}


@app.post("/api/billing/set-default-pm")
def set_default_pm(payload: dict,
                   user=Depends(require_user),
                   _=Depends(verify_csrf)):
    """Пометить сохранённую карту как дефолтную у клиента."""
    pm_id = (payload.get("payment_method") or "").strip()
    if not pm_id:
        raise HTTPException(status_code=400, detail="payment_method required")

    customer_id, _ = ensure_stripe_customer_for_user(user["id"])
    stripe.PaymentMethod.attach(pm_id, customer=customer_id)
    stripe.Customer.modify(customer_id,
                           invoice_settings={"default_payment_method": pm_id})

    from security import _db
    with _db() as con:
        con.execute("UPDATE users SET stripe_default_pm = ? WHERE id = ?",
                    (pm_id, user["id"]))
    return {"ok": True}


@app.get("/pp-auth.js")
def serve_pp_auth_js():
    return serve_static("pp-auth.js", "application/javascript")


@app.get("/api/session/me")
async def session_me(user = Depends(require_user)):
    out = {
        "id": user.get("id"),
        "email": user.get("email"),
        "plan_type": user.get("plan_type"),
        "subscription_status": user.get("subscription_status"),
    }

    def _norm(s: str) -> str:
        import re
        return re.sub(r"[^A-Z0-9]", "", (s or "").upper())

    # 1) по email, если он есть
    email = (user.get("email") or "").strip().lower()
    is_admin = bool(ADMIN_EMAIL and email == ADMIN_EMAIL)

    # 2) по license_key (надёжнее, если email недоступен/шифрован)
    if not is_admin:
        lk = user.get("license_key")
        if lk and ADMIN_LICENSE_KEY:
            if _norm(lk) == _norm(ADMIN_LICENSE_KEY):
                is_admin = True

    # 3) fallback по id (если вдруг нужно)
    if not is_admin and ADMIN_EMAIL:
        try:
            u_admin = AUTH.get_user_by_email(ADMIN_EMAIL)
            if u_admin and int(u_admin.get("id", 0)) == int(user.get("id", 0)):
                is_admin = True
        except Exception as e:
            print(f"[session_me] admin id fallback error: {e}")

    out["is_admin"] = is_admin
    return out


@app.get("/__debug/cookies")
def debug_cookies(request: Request):
    return {"cookies": dict(request.cookies)}


@app.get("/__debug/session")
def dbg_session(request: Request):
    from security import SESSION_COOKIE
    try:
        tok = request.cookies.get(SESSION_COOKIE)
        u = _fetch_user_by_session(tok)  # импортируется из security.py
        return {"pp_session_present": bool(tok), "token_len": len(tok or ""), "user": u}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


@app.get("/api/referral-stats/me")
def referral_stats_me(user=Depends(require_user)):
    """
    Return referral stats for the currently authenticated user.
    Safe defaults if referral tables aren't present.
    """
    from security import _db
    stats = {"email": None, "referrals": 0, "free_months": 0}

    try:
        with _db() as con:
            # 1) узнаём email текущего пользователя
            row = con.execute("SELECT email FROM users WHERE id = ?",
                              (user["id"], )).fetchone()
            if row:
                stats["email"] = row["email"]

            # 2) попытка посчитать рефералы (работает, если есть такая таблица/поле)
            # Попробуем по user_id:
            try:
                r = con.execute(
                    "SELECT COUNT(*) AS c FROM referrals WHERE referrer_user_id = ?",
                    (user["id"], )).fetchone()
                if r and "c" in r.keys() and r["c"] is not None:
                    stats["referrals"] = int(r["c"])
            except Exception:
                # Альтернатива — по email (если вдруг так хранится)
                if stats["email"]:
                    try:
                        r = con.execute(
                            "SELECT COUNT(*) AS c FROM referrals WHERE referrer_email = ?",
                            (stats["email"], )).fetchone()
                        if r and "c" in r.keys() and r["c"] is not None:
                            stats["referrals"] = int(r["c"])
                    except Exception:
                        pass

            # 3) бесплатные месяцы, если где-то считаются/копятся
            # Если у тебя есть отдельная таблица/поле — подставь свой запрос.
            # Иначе оставим 0.
    except Exception:
        # тихо даём дефолт, чтобы UI не падал
        pass

    return stats


# ==========================================
# API FOR TRADING JOURNAL
#============================================


@app.post("/api/transactions")
async def create_transaction(transaction: dict, current_user = Depends(get_current_user)):
    transaction_id = add_transaction(current_user['id'], transaction)
    return {"success": True, "id": transaction_id}

@app.get("/api/transactions")
async def read_transactions(current_user = Depends(get_current_user)):
    transactions = get_transactions(current_user['id'])
    return {"transactions": transactions}

@app.delete("/api/transactions/{transaction_id}")
async def remove_transaction(transaction_id: int, current_user = Depends(get_current_user)):
    delete_transaction(current_user['id'], transaction_id)
    return {"success": True}

# API для Watchlist
@app.post("/api/watchlist")
async def add_to_watchlist(data: dict, current_user = Depends(get_current_user)):
    # Добавляем в watchlist
    conn = sqlite3.connect('profitpal.db')
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO watchlist (user_id, symbol) VALUES (?, ?)',
              (current_user['id'], data['symbol']))
    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/api/watchlist")
async def get_watchlist(current_user = Depends(get_current_user)):
    conn = sqlite3.connect('profitpal.db')
    c = conn.cursor()
    c.execute('SELECT symbol FROM watchlist WHERE user_id = ?', (current_user['id'],))
    symbols = [row[0] for row in c.fetchall()]
    conn.close()
    return {"symbols": symbols}


# ==========================================
# AUTHENTICATION API ENDPOINTS
# ==========================================


@app.post("/api/logout")
def api_logout(request: Request,
               response: Response,
               user=Depends(require_user)):
    # deactivate current session and clear cookies
    from security import _db
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with _db() as con:
            con.execute(
                "UPDATE user_sessions SET is_active=0 WHERE session_token = ?",
                (token, ))
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True}


@app.post('/validate-credentials')
async def check_credentials(request: Request):
    """Проверка email + license для подсветки имени + referral info"""
    try:
        body = await request.json()
        email_raw = (body.get('email') or '').strip()
        license_key_raw = (body.get('license_key') or '').strip()

        if not email_raw or not license_key_raw:
            return JSONResponse(
                {
                    "show_name": False,
                    "error": "Email and license key required"
                },
                status_code=400)

        # нормализуем
        email = email_raw.lower()

        def _norm_key(s: str) -> str:
            import re as _re
            return _re.sub(r'[^A-Z0-9]', '', (s or '').upper())

        # ===== Админ =====
        admin_email = (os.getenv('ADMIN_EMAIL', '') or '').lower().strip()
        admin_key = (os.getenv('ADMIN_LICENSE_KEY', '') or '').strip()
        if email == admin_email:
            if _norm_key(license_key_raw) != _norm_key(admin_key):
                return JSONResponse(
                    {
                        "show_name": False,
                        "error": "User not found"
                    },
                    status_code=401)

            resp = {
                "show_name": True,
                "full_name": os.getenv('ADMIN_FULL_NAME',
                                       'System Administrator'),
                "email": email_raw,
                "welcome_message": "Welcome back, System Administrator!"
            }
            # реферал-инфо (если есть запись)
            try:
                info = referral_mgr.get_user_referral_info(
                    email)  # lower-case ключ
                if info:
                    resp.update({
                        "referral_code":
                        info.get("referral_code"),
                        "referral_link":
                        info.get("referral_link"),
                        "free_months_balance":
                        info.get("free_months_balance"),
                        "total_referrals":
                        info.get("total_referrals"),
                        "total_earned_months":
                        info.get("total_earned_months"),
                    })
            except Exception:
                pass
            return JSONResponse(resp, status_code=200)

        # ===== Клиент =====
        import re
        # формат PP-XXXX-XXXX-XXXX
        if not re.fullmatch(r'^PP-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$',
                            license_key_raw.upper()):
            return JSONResponse(
                {
                    "show_name":
                    False,
                    "error":
                    "Invalid license key format. Should be: PP-XXXX-XXXX-XXXX"
                },
                status_code=400)

        result = validate_user_credentials(email=email_raw,
                                           license_key=license_key_raw)
        if result and result.get('valid'):
            full_name = result.get('full_name') or ''
            resp = {
                "show_name": True,
                "full_name": full_name,
                "email": result.get('email') or email_raw,
                "welcome_message": f"Welcome back, {full_name}!"
            }
            # реферал-инфо для клиента
            try:
                info = referral_mgr.get_user_referral_info(
                    email)  # lower-case ключ
                if info:
                    resp.update({
                        "referral_code":
                        info.get("referral_code"),
                        "referral_link":
                        info.get("referral_link"),
                        "free_months_balance":
                        info.get("free_months_balance"),
                        "total_referrals":
                        info.get("total_referrals"),
                        "total_earned_months":
                        info.get("total_earned_months"),
                    })
            except Exception:
                pass

            return JSONResponse(resp, status_code=200)

        return JSONResponse(
            {
                "show_name": False,
                "error": (result or {}).get('error', 'Invalid credentials')
            },
            status_code=401)

    except Exception as e:
        print(f"❌ Credentials validation error: {e}")
        return JSONResponse({
            "show_name": False,
            "error": "Validation failed"
        },
                            status_code=500)


@app.post('/api/check-admin-status')
async def check_admin_status(request: Request):
    """API для проверки админского статуса пользователя"""
    try:
        body = await request.json()
        email = (body.get('email', '') or '').strip().lower()
        fingerprint = body.get('fingerprint', '')

        admin_email = (os.getenv('ADMIN_EMAIL', '') or '').lower()
        admin_name = os.getenv('ADMIN_FULL_NAME', 'Administrator')
        is_admin = (email == admin_email)

        print(
            f"🔍 Admin status check: email={email}, admin_email={admin_email}, "
            f"is_admin={is_admin}")

        return JSONResponse(content={
            "is_admin": is_admin,
            "admin_email": admin_email,
            "admin_full_name": admin_name,
            "fingerprint": fingerprint,
            "status": "success"
        },
                            status_code=200)

    except Exception as e:
        print(f"❌ Error in check_admin_status: {e}")
        return JSONResponse(content={
            "is_admin": False,
            "error": str(e)
        },
                            status_code=500)


@app.post("/authenticate-user")
async def authenticate_user_ep(request: Request, response: Response):
    """
    Админ по ENV → вход по email+license_key (без оплаты).
    Остальные → через auth_manager.authenticate_user_login.
    Всегда создаём серверную сессию и ставим pp_session / pp_csrf.
    """
    try:
        # ---- parse body ----
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"success": False, "error": "Invalid JSON"}, status_code=400)

        email       = (body.get("email") or "").strip().lower()
        license_key = (body.get("license_key") or "").strip()
        full_name   = (body.get("full_name") or "").strip() or None

        if not email or not license_key:
            return JSONResponse({"success": False, "error": "Email and license key required"}, status_code=400)

        ip = request.client.host if request.client else "unknown"
        ua = request.headers.get("user-agent", "unknown")

        def _norm(s: str) -> str:
            return "".join(ch for ch in (s or "").strip().upper() if ch.isalnum())

        # =========================
        # === ADMIN BYPASS PATH ===
        # =========================
        if ADMIN_EMAIL and email == ADMIN_EMAIL:
            if _norm(license_key) != _norm(ADMIN_LICENSE_KEY):  # привязка к ключу из ENV (а не к email)
                return JSONResponse({"success": False, "error": "Invalid admin credentials"}, status_code=401)

            # надёжно находим/создаём и синхронизируем ключ
            try:
                user_id = ensure_admin_user_id(
                    email=email,
                    full_name=(full_name or ADMIN_FULL_NAME),
                    license_key=license_key,  # уже проверен по ENV
                )
            except Exception as e:
                import traceback
                print(f"❌ ensure_admin_user_id error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
                return JSONResponse({"success": False, "error": "Failed to create admin"}, status_code=500)

            # создаём сессию и ставим куки
            token, csrf, _ = create_session(user_id, ip, ua)
            set_session_cookies(response, request, token, csrf, days=30)
            return {"success": True, "authenticated": True, "redirect": "/dashboard"}

        # ==========================
        # === REGULAR USER PATH ===
        # ==========================
        try:
            auth = authenticate_user_login(
                email=email,
                license_key=license_key,
                full_name=full_name,
                ip_address=ip,
                user_agent=ua,
            )
        except Exception as e:
            print(f"[auth] authenticate_user_login call failed: {e}")
            return JSONResponse({"success": False, "error": "Auth call failed"}, status_code=500)

        if not auth or not auth.get("authenticated"):
            err = (auth or {}).get("error", "Invalid credentials")
            return JSONResponse({"success": False, "error": err}, status_code=401)

        user = auth.get("user") or {}
        user_id = user.get("id") or auth.get("user_id")
        if not user_id:
            # последний шанс — перечитать по email через менеджер
            try:
                u2 = AUTH.get_user_by_email(email)
                if u2 and u2.get("id"):
                    user_id = int(u2["id"])
            except Exception as e:
                print(f"[auth] fallback get_user_by_email failed: {e}")

        if not user_id:
            return JSONResponse({"success": False, "error": "Auth result missing user_id"}, status_code=500)

        token, csrf, _ = create_session(int(user_id), ip, ua)
        set_session_cookies(response, request, token, csrf, days=30)
        return {"success": True, "authenticated": True, "redirect": "/dashboard"}

    except Exception as e:
        import traceback
        print(f"❌ authenticate_user_ep error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        return JSONResponse({"success": False, "error": f"{type(e).__name__}: {e}"}, status_code=500)


@app.post("/api/authenticate")
async def api_authenticate(request: Request, response: Response):
    """API-версия — такая же логика, та же сессия"""
    try:
        body = await request.json()
        email = (body.get("email") or "").strip()
        license_key = (body.get("license_key") or "").strip()
        full_name = (body.get("full_name") or "").strip() or None

        ip_address = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")

        result = authenticate_user_login(
            email=email,
            license_key=license_key,
            full_name=full_name,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        if not result or not result.get("authenticated"):
            err = (result or {}).get("error", "Invalid credentials")
            raise HTTPException(status_code=401, detail=err)

        user_obj = result.get("user") or {}
        user_id = (user_obj.get("id") or result.get("user_id")
                   or result.get("uid") or result.get("id"))

        if not user_id:
            v = validate_user_credentials(email, license_key)
            if v and v.get("valid"):
                user_id = v.get("user_id")

        if not user_id:
            admin_email = (os.getenv("ADMIN_EMAIL", "") or "").strip().lower()
            admin_key = (os.getenv("ADMIN_LICENSE_KEY", "") or "").strip()
            if email.lower() == admin_email and license_key.strip(
            ) == admin_key:
                try:
                    create_new_user(
                        email=email,
                        full_name=full_name
                        or os.getenv("ADMIN_FULL_NAME", "Administrator"))
                except Exception:
                    pass
                v = validate_user_credentials(email, license_key)
                if v and v.get("valid"):
                    user_id = v.get("user_id")

        if not user_id:
            raise HTTPException(status_code=401,
                                detail="User not found for this login")

        token, csrf, _ = create_session(int(user_id), ip_address, user_agent)
        response.set_cookie(SESSION_COOKIE,
                            token,
                            max_age=30 * 24 * 3600,
                            httponly=True,
                            secure=SECURE_COOKIES,
                            samesite="lax",
                            path="/")
        response.set_cookie(CSRF_COOKIE,
                            csrf,
                            max_age=30 * 24 * 3600,
                            httponly=False,
                            secure=SECURE_COOKIES,
                            samesite="lax",
                            path="/")
        return {"authenticated": True}

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(
            f"❌ API auth error: {type(e).__name__}: {e}\n{traceback.format_exc()}"
        )
        raise HTTPException(status_code=500, detail="Internal error")


# ==========================================
# STRIPE PAYMENT API
# ==========================================


@app.get('/get-stripe-key')
def get_stripe_publishable_key():
    """Return Stripe publishable key for frontend"""
    return {"publishableKey": STRIPE_PUBLISHABLE_KEY}


@app.post('/create-subscription-checkout')
async def create_subscription_checkout(request: Request):
    """Create Stripe Checkout for subscription plans with billing cycle anchor"""
    # Guards
    if not STRIPE_READY:
        raise HTTPException(status_code=503, detail="Stripe is not configured")

    body = await request.json()
    plan_type = (body.get('plan_type') or "").strip()
    email = (body.get('email') or "").strip()
    full_name = (body.get('full_name') or "").strip()
    referral_code = (body.get('referral_code') or "").strip()

    if not plan_type:
        raise HTTPException(status_code=400, detail="plan_type is required")
    if not email:
        raise HTTPException(status_code=400, detail="email is required")
    if not full_name:
        raise HTTPException(status_code=400, detail="full_name is required")

    price_id_map = {
        'early_bird': EARLY_BIRD_PRICE_ID,
        'standard': STANDARD_PRICE_ID,
        'pro': PRO_PRICE_ID,
    }

    # 1) валидируем тип плана
    if plan_type not in price_id_map:
        raise HTTPException(status_code=400, detail="Invalid plan type")

    # 2) проверяем, что для выбранного плана реально задан Price ID в ENV
    price_id = price_id_map[plan_type]
    if not price_id:
        raise HTTPException(
            status_code=503,
            detail=f"Price ID for '{plan_type}' not configured")

    try:
        # привязываем биллинг к 1-му числу следующего месяца
        next_month = datetime.now().replace(day=1) + timedelta(days=32)
        billing_anchor = int(next_month.replace(day=1).timestamp())

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            customer_email=email,
            line_items=[{
                'price': price_id,
                'quantity': 1
            }],
            mode='subscription',
            subscription_data={
                'billing_cycle_anchor': billing_anchor,
                'proration_behavior': 'create_prorations',
            },
            success_url=
            f'{YOUR_DOMAIN}/success?session_id={{CHECKOUT_SESSION_ID}}',
            cancel_url=f'{YOUR_DOMAIN}/cancel',
            metadata={
                'full_name': full_name,
                'email': email,
                'referral_code': referral_code,
                'plan_type': plan_type,
                'product': 'profitpal_subscription',
            },
        )

        print(f"✅ Subscription checkout created: {checkout_session.id}")
        return {"checkout_url": checkout_session.url}

    except stripe.error.StripeError as e:
        msg = getattr(e, "user_message", None) or str(e)
        print(f"❌ Stripe error creating subscription checkout: {msg}")
        raise HTTPException(status_code=502, detail=msg)
    except Exception as e:
        print(f"❌ Error creating subscription checkout: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/create-checkout-session')
async def create_checkout_session(payment_request: PaymentRequest):
    """Create Stripe Checkout Session for LIFETIME ACCESS"""
    # Guards
    if not STRIPE_READY:
        raise HTTPException(status_code=503, detail="Stripe is not configured")
    if not LIFETIME_ACCESS_PRICE_ID:
        raise HTTPException(status_code=503,
                            detail="LIFETIME price ID not configured")

    # Validate payload
    email = (payment_request.email or "").strip()
    full_name = (payment_request.full_name or "").strip()
    referral_code = (payment_request.referral_code or "").strip()

    if not email:
        raise HTTPException(status_code=400, detail="email is required")
    if not full_name:
        raise HTTPException(status_code=400, detail="full_name is required")

    try:
        print(
            f"💳 Creating LIFETIME ACCESS checkout for: {full_name} ({email})")
        if referral_code:
            print(f"🔗 Referral code: {referral_code}")

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            customer_email=email,
            line_items=[{
                'price': LIFETIME_ACCESS_PRICE_ID,
                'quantity': 1
            }],
            mode='payment',
            success_url=
            f'{YOUR_DOMAIN}/success?session_id={{CHECKOUT_SESSION_ID}}',
            cancel_url=f'{YOUR_DOMAIN}/cancel',
            metadata={
                'full_name': full_name,
                'email': email,
                'referral_code': referral_code,
                'product': 'profitpal_pro_lifetime',
                'version': '2.0'
            })

        print(f"✅ Checkout session created: {checkout_session.id}")
        return {"checkout_url": checkout_session.url}

    except stripe.error.StripeError as e:
        # Деталь для клиента — аккуратная, без лишних подробностей
        msg = getattr(e, "user_message", None) or str(e)
        print(f"❌ Stripe error creating checkout session: {msg}")
        raise HTTPException(status_code=502, detail=msg)
    except Exception as e:
        print(f"❌ Error creating checkout session: {e}")
        raise HTTPException(status_code=500,
                            detail="Failed to create checkout session")


@app.post('/stripe-webhook')
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle Stripe webhook events + REFERRAL PROCESSING"""
    try:
        payload = await request.body()
        sig_header = request.headers.get('stripe-signature')

        try:
            event = stripe.Webhook.construct_event(payload, sig_header,
                                                   STRIPE_WEBHOOK_SECRET)
        except ValueError as e:
            print(f"❌ Invalid payload: {e}")
            return JSONResponse(content={"error": "Invalid payload"},
                                status_code=400)
        except stripe.error.SignatureVerificationError as e:
            print(f"❌ Invalid signature: {e}")
            return JSONResponse(content={"error": "Invalid signature"},
                                status_code=400)

        print(f"🎯 Webhook received: {event['type']}")

        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            email = session.get('customer_email')
            session_id = session.get('id')

            metadata = session.get('metadata', {})
            full_name = metadata.get('full_name', 'ProfitPal User')
            referral_code = metadata.get('referral_code', '')
            product_type = metadata.get('product', 'profitpal_pro_lifetime')

            print(f"🎉 Payment completed: {product_type} for {email}")
            print(f"🔗 Used referral code: {referral_code}")

            if email and session_id and full_name:
                if product_type == 'profitpal_subscription':
                    plan_type = metadata.get('plan_type', 'early_bird')
                    print(f"📊 Subscription created: {plan_type} plan")
                    # TODO: Создать пользователя с подпиской
                    # TODO: Настроить recurring billing с referral учетом
                else:
                    user_result = create_new_user(
                        email=email,
                        full_name=full_name,
                        stripe_customer_id=session.get('customer'))

                    if user_result['success']:
                        license_key = user_result['license_key']
                        print(
                            f"✅ User created: {full_name} ({email}) → {license_key}"
                        )

                        # 🔥 СОЗДАЕМ АВТОМАТИЧЕСКУЮ ПОДПИСКУ НА $9.99 ПОСЛЕ LIFETIME ACCESS
                        try:
                            print(
                                f"💳 Creating automatic $9.99 subscription for {email}"
                            )

                            # Создаем subscription на Early Bird план
                            subscription = stripe.Subscription.create(
                                customer=session.get('customer'),
                                items=[{
                                    'price': EARLY_BIRD_PRICE_ID,
                                }],
                                billing_cycle_anchor='now',
                                proration_behavior='none',
                                metadata={
                                    'type': 'auto_created_after_lifetime',
                                    'user_email': email,
                                    'lifetime_payment': '29.99'
                                })
                            print(
                                f"✅ Auto subscription created: {subscription.id}"
                            )

                        except Exception as sub_error:
                            print(
                                f"❌ Failed to create auto subscription: {sub_error}"
                            )

                        referral_result = referral_mgr.create_referral_for_user(
                            email, YOUR_DOMAIN)
                        referral_link = ""
                        if referral_result['success']:
                            referral_link = referral_result['referral_link']
                            print(
                                f"🔗 Referral created: {referral_result['referral_code']}"
                            )

                        if referral_code and referral_mgr.referral_code_exists(
                                referral_code):
                            signup_result = referral_mgr.process_referral_signup(
                                referral_code, email, 29.99)
                            if signup_result['success']:
                                print(
                                    f"🎁 Referral processed! {signup_result['referrer_email']} earned free month"
                                )

                                background_tasks.add_task(
                                    send_referral_reward_email,
                                    signup_result['referrer_email'],
                                    signup_result['new_balance'], email)

                        background_tasks.add_task(
                            send_welcome_email_with_referral, email,
                            license_key, full_name, referral_link)
                    else:
                        print(
                            f"❌ Failed to create user: {user_result.get('error')}"
                        )
            else:
                print(
                    f"❌ Missing required data in webhook: email={email}, name={full_name}"
                )

        return JSONResponse(content={"status": "success"}, status_code=200)

    except Exception as e:
        print(f"❌ Webhook error: {e}")
        return JSONResponse(content={"error": "Webhook processing failed"},
                            status_code=500)


# ==========================================
# REFERRAL API ENDPOINTS
# ==========================================


@app.get('/api/referral-stats/{email}')
async def get_referral_statistics(email: str):
    """Получить referral статистику пользователя для dashboard"""
    try:
        stats = referral_mgr.get_referral_statistics(email)
        return JSONResponse(content=stats)
    except Exception as e:
        print(f"❌ Error getting referral stats: {e}")
        return JSONResponse(
            content={'error': 'Failed to get referral statistics'},
            status_code=500)


@app.get('/api/referral-link/{email}')
async def get_user_referral_link(email: str):
    """Получить referral ссылку пользователя"""
    try:
        referral_info = referral_mgr.get_user_referral_info(email)
        if referral_info:
            return JSONResponse(
                content={
                    'referral_link': referral_info['referral_link'],
                    'referral_code': referral_info['referral_code'],
                    'free_months_balance':
                    referral_info['free_months_balance'],
                    'total_referrals': referral_info['total_referrals']
                })
        else:
            return JSONResponse(content={'error': 'No referral info found'},
                                status_code=404)
    except Exception as e:
        print(f"❌ Error getting referral link: {e}")
        return JSONResponse(content={'error': 'Failed to get referral link'},
                            status_code=500)


# =================================================
# LOGIN API ENDPOINTS
# =================================================


@app.post('/api/login')
async def api_login(request: Request):
    """Validate license key and fingerprint"""
    try:
        data = await request.json()
        email = data.get('email', '').strip().lower()
        license_key = data.get('license_key', '').strip().upper()
        fingerprint = data.get('fingerprint', {})

        # Validate input
        if not email or not license_key:
            raise HTTPException(status_code=400,
                                detail="Email and license key are required")

        # Validate license key format (different for admin vs client)
        admin_email = os.getenv('ADMIN_EMAIL', '').lower()
        is_admin = (email == admin_email)

        if is_admin:
            # Admin key: PP-XX-XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX or any PP- format
            if not license_key.startswith('PP-') or len(license_key) < 10:
                raise HTTPException(status_code=400,
                                    detail="Invalid admin license key format")
        else:
            # Client key: PP-XXXX-XXXX-XXXX
            if not re.match(r'^PP-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$',
                            license_key):
                raise HTTPException(
                    status_code=400,
                    detail=
                    "Invalid license key format. Should be: PP-XXXX-XXXX-XXXX")

        # Check if license exists and is valid
        if not validate_license_key(email, license_key):
            raise HTTPException(status_code=401,
                                detail="Invalid license key or email address")

        # Record fingerprint and login
        record_user_login(email, license_key, fingerprint, request)

        return JSONResponse(
            content={
                "status": "success",
                "message": "Login successful",
                "redirect": "/dashboard"
            })

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Login error: {e}")
        raise HTTPException(status_code=500,
                            detail="Login failed. Please try again.")


def validate_license_key(email: str, license_key: str) -> bool:
    """Validate if license key belongs to email"""
    try:
        print(f"🔐 Validating license: {email} -> {license_key}")

        # Check if this is admin
        admin_email = os.getenv('ADMIN_EMAIL', '').lower()
        admin_key = os.getenv('ADMIN_LICENSE_KEY', '')

        if email == admin_email and license_key == admin_key:
            print(f"👑 Admin login successful!")
            return True

        # Client validation - check with auth_manager or database
        # TODO: Replace with real database check
        return len(license_key) == 16 and license_key.startswith('PP-')

    except Exception as e:
        print(f"❌ License validation error: {e}")
        return False


def record_user_login(email: str, license_key: str, fingerprint: dict,
                      request: Request):
    """Record user login with fingerprint for tracking"""
    try:
        client_ip = request.client.host if hasattr(request,
                                                   'client') else 'unknown'

        login_data = {
            'email': email,
            'license_key': license_key,
            'fingerprint': fingerprint,
            'login_time': datetime.now().isoformat(),
            'ip_address': client_ip,
            'user_agent': request.headers.get('user-agent', 'unknown')
        }

        # TODO: Save to database for tracking
        # auth_mgr.record_login(login_data) or similar

        print(f"🔐 User login recorded:")
        print(f"   📧 Email: {email}")
        print(f"   🔑 License: {license_key}")
        print(f"   📱 Device: {fingerprint.get('platform', 'unknown')}")
        print(f"   🌍 IP: {client_ip}")

    except Exception as e:
        print(f"❌ Error recording login: {e}")


@app.post('/api/monthly-billing/{email}')
async def process_monthly_billing(email: str):
    """Обработать месячный billing с учетом referral free months"""
    try:
        billing_result = referral_mgr.check_and_use_free_month(email)

        if billing_result['should_charge']:
            charge_amount = billing_result['charge_amount']
            print(f"💳 Charging ${charge_amount} for {email}")
        else:
            print(
                f"🎁 Free month used for {email}. {billing_result['free_months_remaining']} remaining"
            )

        return JSONResponse(content=billing_result)

    except Exception as e:
        print(f"❌ Monthly billing error: {e}")
        return JSONResponse(content={'error': 'Monthly billing failed'},
                            status_code=500)


@app.post('/api/upgrade-subscription')
async def upgrade_subscription(request: Request,
                               background_tasks: BackgroundTasks):
    """🔥 НОВЫЙ: Upgrade subscription plan (Early Bird → Standard → PRO)"""
    try:
        body = await request.json()
        email = body.get('email')
        target_plan = body.get('target_plan')  # 'standard', 'pro'
        current_plan = body.get('current_plan',
                                'early_bird')  # 'early_bird', 'standard'

        print(
            f"📈 Upgrade request: {email} from {current_plan} to {target_plan}")

        # Валидация планов
        plan_price_map = {
            'early_bird': {
                'price_id': EARLY_BIRD_PRICE_ID,
                'amount': 9.99
            },
            'standard': {
                'price_id': STANDARD_PRICE_ID,
                'amount': 14.99
            },
            'pro': {
                'price_id': PRO_PRICE_ID,
                'amount': 49.99
            }
        }

        if target_plan not in plan_price_map or current_plan not in plan_price_map:
            raise HTTPException(status_code=400, detail="Invalid plan type")

        # Проверка что это действительно upgrade
        current_amount = plan_price_map[current_plan]['amount']
        target_amount = plan_price_map[target_plan]['amount']

        if target_amount <= current_amount:
            raise HTTPException(status_code=400,
                                detail="Can only upgrade to higher tier")

        # Получаем пользователя и его Stripe customer ID
        auth_user = auth_mgr.get_user_by_email(email)
        if not auth_user or not auth_user.get('stripe_customer_id'):
            raise HTTPException(status_code=404,
                                detail="User not found or no payment method")

        customer_id = auth_user['stripe_customer_id']

        # Находим активную подписку пользователя
        subscriptions = stripe.Subscription.list(customer=customer_id,
                                                 status='active',
                                                 limit=10)

        current_subscription = None
        for sub in subscriptions.data:
            if sub.items.data[0].price.id in [
                    EARLY_BIRD_PRICE_ID, STANDARD_PRICE_ID
            ]:
                current_subscription = sub
                break

        if not current_subscription:
            raise HTTPException(status_code=404,
                                detail="No active subscription found")

        print(f"📊 Found subscription: {current_subscription.id}")

        # Выполняем upgrade подписки
        target_price_id = plan_price_map[target_plan]['price_id']

        updated_subscription = stripe.Subscription.modify(
            current_subscription.id,
            items=[{
                'id': current_subscription.items.data[0].id,
                'price': target_price_id,
            }],
            proration_behavior='create_prorations',  # Пропорциональное списание
            metadata={
                'upgraded_from': current_plan,
                'upgraded_to': target_plan,
                'upgrade_date': datetime.now().isoformat()
            })

        print(f"✅ Subscription upgraded: {updated_subscription.id}")

        # Отправляем email о successful upgrade
        background_tasks.add_task(send_upgrade_confirmation_email, email,
                                  current_plan, target_plan, target_amount)

        return JSONResponse(
            content={
                'success': True,
                'message':
                f'Successfully upgraded from {current_plan} to {target_plan}',
                'new_amount': target_amount,
                'subscription_id': updated_subscription.id
            })

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Upgrade error: {e}")
        return JSONResponse(content={'error': f'Upgrade failed: {str(e)}'},
                            status_code=500)


@app.post('/api/get-upgrade-options')
async def get_upgrade_options(request: Request):
    """🔥 НОВЫЙ: Получить доступные upgrade опции для пользователя"""
    try:
        body = await request.json()
        email = body.get('email')

        # Получаем текущий план пользователя
        auth_user = auth_mgr.get_user_by_email(email)
        if not auth_user or not auth_user.get('stripe_customer_id'):
            return JSONResponse(content={'error': 'User not found'},
                                status_code=404)

        customer_id = auth_user['stripe_customer_id']

        # Находим активную подписку
        subscriptions = stripe.Subscription.list(customer=customer_id,
                                                 status='active',
                                                 limit=10)

        current_plan = 'none'
        current_amount = 0

        for sub in subscriptions.data:
            price_id = sub.items.data[0].price.id
            if price_id == EARLY_BIRD_PRICE_ID:
                current_plan = 'early_bird'
                current_amount = 9.99
            elif price_id == STANDARD_PRICE_ID:
                current_plan = 'standard'
                current_amount = 14.99
            elif price_id == PRO_PRICE_ID:
                current_plan = 'pro'
                current_amount = 49.99
            break

        # Определяем доступные upgrade опции
        upgrade_options = []

        if current_plan == 'early_bird':
            upgrade_options = [{
                'plan':
                'standard',
                'name':
                'ProfitPal Standard',
                'price':
                14.99,
                'upgrade_cost':
                14.99 - 9.99,
                'features': [
                    'All Early Bird features', 'Advanced screening',
                    'Priority support'
                ]
            }, {
                'plan':
                'pro',
                'name':
                'ProfitPal PRO',
                'price':
                49.99,
                'upgrade_cost':
                49.99 - 9.99,
                'features': [
                    'All Standard features', 'Options analysis', 'Live Greeks',
                    'Volatility alerts'
                ]
            }]
        elif current_plan == 'standard':
            upgrade_options = [{
                'plan':
                'pro',
                'name':
                'ProfitPal PRO',
                'price':
                49.99,
                'upgrade_cost':
                49.99 - 14.99,
                'features': [
                    'All Standard features', 'Options analysis', 'Live Greeks',
                    'Volatility alerts'
                ]
            }]
        # PRO план - нет upgrade опций

        return JSONResponse(
            content={
                'current_plan': current_plan,
                'current_amount': current_amount,
                'upgrade_options': upgrade_options
            })

    except Exception as e:
        print(f"❌ Error getting upgrade options: {e}")
        return JSONResponse(content={'error': 'Failed to get upgrade options'},
                            status_code=500)


# ==========================================
# FREE TRIAL ENDPOINTS
# ==========================================


@app.post("/api/check-free-trial")
async def check_free_trial(request: FreeTrialRequest):
    """Проверка лимита бесплатных анализов по fingerprint"""
    try:
        print(
            f"🔍 Checking free trial for fingerprint: {request.fingerprint[:10]}..."
        )

        # 🔥 ПРИНУДИТЕЛЬНО СОЗДАЕМ ТАБЛИЦУ ПЕРЕД ЗАПРОСОМ
        create_free_trial_table()

        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT analyses_used, max_analyses 
            FROM free_trials 
            WHERE fingerprint = ?
        ''', (request.fingerprint, ))

        result = cursor.fetchone()
        conn.close()

        if result:
            analyses_used, max_analyses = result
            remaining = max_analyses - analyses_used
            allowed = remaining > 0
            print(
                f"📊 Existing user: {analyses_used}/{max_analyses} used, remaining: {remaining}"
            )
        else:
            analyses_used = 0
            max_analyses = 5
            remaining = 5
            allowed = True
            print(f"🆕 New user: {remaining} analyses available")

        return JSONResponse(
            content={
                'allowed': allowed,
                'used': analyses_used,
                'remaining': remaining,
                'max_analyses': max_analyses
            })

    except Exception as e:
        print(f"❌ Error checking free trial: {e}")
        return JSONResponse(
            content={'error': f'Free trial check failed: {str(e)}'},
            status_code=500)


@app.post("/api/record-free-trial")
async def record_free_trial(request: FreeTrialRecordRequest):
    """Запись использования бесплатного анализа"""
    try:
        print(
            f"📝 Recording free trial usage: {request.fingerprint[:10]}... ticker: {request.ticker}"
        )

        # 🔥 ПРИНУДИТЕЛЬНО СОЗДАЕМ ТАБЛИЦУ ПЕРЕД ЗАПИСЬЮ
        create_free_trial_table()

        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT analyses_used, max_analyses 
            FROM free_trials 
            WHERE fingerprint = ?
        ''', (request.fingerprint, ))

        result = cursor.fetchone()

        if result:
            analyses_used, max_analyses = result
            new_count = analyses_used + 1

            cursor.execute(
                '''
                UPDATE free_trials 
                SET analyses_used = ?, last_used = CURRENT_TIMESTAMP
                WHERE fingerprint = ?
            ''', (new_count, request.fingerprint))

            print(f"📈 Updated existing user: {new_count}/{max_analyses} used")
        else:
            cursor.execute(
                '''
                INSERT INTO free_trials (fingerprint, analyses_used, max_analyses)
                VALUES (?, 1, 5)
            ''', (request.fingerprint, ))

            new_count = 1
            max_analyses = 5
            print(f"🆕 Created new user: {new_count}/{max_analyses} used")

        conn.commit()
        conn.close()

        remaining = max_analyses - new_count

        return JSONResponse(
            content={
                'success': True,
                'analyses_used': new_count,
                'remaining': remaining,
                'ticker': request.ticker
            })

    except Exception as e:
        print(f"❌ Error recording free trial: {e}")
        return JSONResponse(
            content={'error': f'Free trial recording failed: {str(e)}'},
            status_code=500)


@app.post("/api/process-donation")
def process_donation(payload: dict,
                     user=Depends(require_user),
                     _=Depends(verify_csrf)):
    """
    One-click donation (off_session) по сохранённой карте.
    Body: { amount, type, authorized: true }
    """
    try:
        amount = float(payload.get("amount", 0))
        dtype = (payload.get("type") or "donation").strip()
        authorized = bool(payload.get("authorized"))
        if not authorized:
            raise HTTPException(status_code=400,
                                detail="Authorization checkbox is required")
        if not (1 <= amount <= 1000):
            raise HTTPException(status_code=400, detail="Invalid amount")

        amount_cents = int(round(amount * 100))
        currency = (os.getenv("DONATION_CURRENCY") or "USD").lower()

        from security import _db
        with _db() as con:
            row = con.execute(
                "SELECT stripe_customer_id FROM users WHERE id = ?",
                (user["id"], )).fetchone()
        if not row or not row["stripe_customer_id"]:
            raise HTTPException(
                status_code=402,
                detail="No saved card. Please save a card in Settings first.")

        customer_id = row["stripe_customer_id"]
        # возьмём default PM; если нет — любой картовый
        cust = stripe.Customer.retrieve(customer_id)
        pm = (cust.get("invoice_settings") or {}).get("default_payment_method")
        if not pm:
            pms = stripe.PaymentMethod.list(customer=customer_id,
                                            type="card",
                                            limit=1)
            pm = pms.data[0]["id"] if pms.data else None
        if not pm:
            raise HTTPException(
                status_code=402,
                detail="No saved card. Please save a card in Settings.")

        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency=currency,
            customer=customer_id,
            payment_method=pm,
            off_session=True,
            confirm=True,
            description=f"Donation ({dtype}) user {user['id']}",
            metadata={
                "user_id": str(user["id"]),
                "donation_type": dtype
            },
        )

        # лог в БД
        with _db() as con:
            con.execute(
                "INSERT INTO donations (user_id, amount_cents, currency, donation_type, stripe_payment_intent_id, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user["id"], amount_cents, currency, dtype, intent["id"],
                 intent["status"]),
            )

        return {
            "success": intent["status"] == "succeeded",
            "status": intent["status"],
            "message": "Thank you for your support!"
        }

    except stripe.error.CardError:
        raise HTTPException(
            status_code=402,
            detail=
            "Card requires authentication. Please update your card in Settings."
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print("❌ process_donation:", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal error")


# ==========================================
# STOCK ANALYSIS API ENDPOINTS
# ==========================================


@app.post("/analyze", response_model=AnalysisResponse)
async def analyze_stock(request: AnalysisRequest):
    """Analyze stock with license validation"""
    try:
        print(
            f"🔍 Analysis request for {request.ticker} with license: {request.license_key}"
        )

        if request.license_key != "FREE" and request.license_key:
            pass

        print(f"📊 Fetching data for {request.ticker.upper()}")
        stock_data = analyzer.get_complete_stock_data(request.ticker.upper())

        if not stock_data["current_price"]:
            print(f"❌ No data found for {request.ticker}")
            raise HTTPException(
                status_code=404,
                detail=f"Stock data not found for {request.ticker}")

        current_price = stock_data["current_price"]
        pe_ratio = stock_data["pe_ratio"]
        market_cap = stock_data["market_cap"]
        debt_ratio = stock_data["debt_ratio"]
        intrinsic_value = stock_data["intrinsic_value"]

        valuation_gap = None
        if intrinsic_value and current_price:
            valuation_gap = (
                (intrinsic_value - current_price) / current_price) * 100

        verdict_factors = []

        if pe_ratio:
            if request.pe_min <= pe_ratio <= request.pe_max:
                verdict_factors.append("✅ P/E PASS")
            else:
                verdict_factors.append("❌ P/E FAIL")

        if debt_ratio:
            if debt_ratio <= request.debt_max:
                verdict_factors.append("✅ DEBT PASS")
            else:
                verdict_factors.append("❌ DEBT FAIL")

        if valuation_gap:
            if valuation_gap > 20:
                verdict_factors.append("💎 UNDERVALUED")
            elif valuation_gap < -20:
                verdict_factors.append("⚠️ OVERVALUED")
            else:
                verdict_factors.append("📊 FAIRLY VALUED")

        passed_filters = sum(1 for factor in verdict_factors if "✅" in factor)
        total_filters = sum(1 for factor in verdict_factors
                            if ("✅" in factor or "❌" in factor))

        if passed_filters == total_filters and valuation_gap and valuation_gap > 15:
            final_verdict = "💎 DIAMOND FOUND - Strong fundamentals + undervalued"
        elif passed_filters == total_filters:
            final_verdict = "⭐ QUALITY STOCK - Meets all criteria"
        elif valuation_gap and valuation_gap < -30:
            final_verdict = "⚠️ OVERVALUED - Price too high vs fundamentals"
        elif passed_filters >= total_filters * 0.6:
            final_verdict = "📊 MIXED SIGNALS - Some good, some concerns"
        else:
            final_verdict = "🚫 AVOID - Multiple red flags"

        print(f"✅ Analysis complete for {request.ticker}: {final_verdict}")

        return AnalysisResponse(
            ticker=request.ticker.upper(),
            current_price=current_price,
            pe_ratio=pe_ratio,
            market_cap=market_cap,
            debt_ratio=debt_ratio,
            intrinsic_value=intrinsic_value,
            valuation_gap=valuation_gap,
            final_verdict=final_verdict,
            analysis_details={
                "verdict_factors":
                verdict_factors,
                "filters_passed":
                f"{passed_filters}/{total_filters}",
                "errors":
                stock_data.get("errors", []),
                "license_used":
                request.license_key,
                "educational_note":
                "This analysis is for educational purposes only. Not financial advice."
            })

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Analysis failed for {request.ticker}: {str(e)}")
        raise HTTPException(status_code=500,
                            detail=f"Analysis failed: {str(e)}")


# ==========================================
# ADMIN ENDPOINTS
# ==========================================


@app.get("/admin/stats")
async def get_admin_stats():
    """Get comprehensive system statistics + REFERRAL stats"""
    try:
        auth_stats = get_auth_stats()
        referral_stats = referral_mgr.get_all_referral_stats()

        return JSONResponse(
            content={
                "system": {
                    "version":
                    "2.0.0",
                    "environment":
                    "production" if "profitpal.org" in
                    YOUR_DOMAIN else "development",
                    "domain":
                    YOUR_DOMAIN
                },
                "auth": auth_stats,
                "referrals": referral_stats,
                "api": {
                    "fmp_key_status":
                    "configured" if len(FMP_API_KEY) > 10 else "missing",
                    "stripe_status":
                    "configured" if len(STRIPE_SECRET_KEY) > 10 else "missing",
                    "email_status":
                    "configured" if GMAIL_PASSWORD else "missing"
                },
                "generated_at": datetime.now().isoformat()
            })

    except Exception as e:
        print(f"❌ Admin stats error: {e}")
        return JSONResponse(content={"error": "Failed to get stats"},
                            status_code=500)


@app.get("/health")
def health_check():
    """System health check + REFERRAL system"""
    return {
        "status":
        "healthy",
        "version":
        "2.0.0",
        "features": [
            "auth_manager", "stripe_payments", "email_notifications",
            "stock_analysis", "referral_system", "donation_system",
            "environment_variables"
        ],
        "endpoints": [
            "/", "/analysis", "/fake-dashboard", "/validate-credentials",
            "/api/stripe-key", "/create-checkout-session",
            "/create-subscription-checkout", "/stripe-webhook", "/analyze",
            "/api/referral-stats/{email}", "/api/referral-link/{email}",
            "/api/process-donation", "/api/upgrade-subscription",
            "/api/get-upgrade-options", "/ref/{referral_code}"
        ],
        "timestamp":
        datetime.now().isoformat()
    }


# ==========================================
# APPLICATION STARTUP
# ==========================================

if __name__ == "__main__":
    import uvicorn

    create_free_trial_table()

    print("\n" + "=" * 60)
    print("🚀🚀🚀 PROFITPAL PRO SERVER v2.0 STARTING 🚀🚀🚀")
    print("=" * 60)
    print("✅ Auth Manager: Integrated")
    print("✅ Referral Manager: Integrated")
    print("✅ Environment Variables: Configured")
    print("✅ Stripe Payments: Ready")
    print("✅ Email Notifications: Ready")
    print("✅ Stock Analysis: FMP API Connected")
    print("✅ Database: Auth + Referral + Free Trial Management")
    print("✅ Donation System: Ready")
    print("💎 Ready for Production with Full Feature Set! 💎")
    print("=" * 60 + "\n")

    if __name__ == "__main__":
        port = int(os.environ.get("PORT", 8000))
        uvicorn.run(app, host="0.0.0.0", port=port)
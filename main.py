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
from fastapi import FastAPI, HTTPException, Request, Form, BackgroundTasks
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import re

# ==========================================
# MANAGERS INTEGRATION
# ==========================================
from auth_manager import validate_user_credentials, create_new_user, authenticate_user_login, get_auth_stats
from referral_manager import ReferralManager  # 🔥 НОВЫЙ IMPORT!

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

# Get API keys from environment variables (Railway secrets)
FMP_API_KEY = os.getenv("FMP_API_KEY", "re6q6DqcjkmRuiXE0fNiDHIYwVH3DcfC")  # Free key as fallback
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "sk_test_fallback")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "pk_test_fallback") 
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_fallback")
GMAIL_EMAIL = os.getenv("GMAIL_EMAIL", "denava.business@gmail.com")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")  # App password for Gmail
YOUR_DOMAIN = os.getenv("DOMAIN", "https://profitpal.org")

# Configure Stripe
stripe.api_key = STRIPE_SECRET_KEY

print("✅ Environment variables loaded!")
print(f"🔑 FMP API Key: {FMP_API_KEY[:15]}...")
print(f"💳 Stripe Keys: Configured")
print(f"🌐 Domain: {YOUR_DOMAIN}")
print(f"📧 Gmail: {GMAIL_EMAIL}")

# ==========================================
# FASTAPI APPLICATION SETUP
# ==========================================

app = FastAPI(
    title="💎 ProfitPal Pro API v2.0",
    description="Professional stock analysis platform with Diamond Rating System + Referral System",
    version="2.0.0"
)

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

# 🔥 INITIALIZE REFERRAL MANAGER!
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

# 🔥 НОВАЯ МОДЕЛЬ ДЛЯ PAYMENT С REFERRAL!
class PaymentRequest(BaseModel):
    email: str
    full_name: str
    referral_code: Optional[str] = None

# 🔥 ДОБАВЬ СЮДА DONATION CLASS:
class DonationRequest(BaseModel):
    amount: float
    type: str  # 'coffee', 'milk', 'features', 'custom'
    email: str

# 🔍 FREE TRIAL FINGERPRINT MODELS
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

    def extract_fmp_value(self, data: Optional[Dict], field_name: str) -> Optional[float]:
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

    def calculate_intrinsic_value(self, ticker: str, current_price: float) -> Tuple[Optional[float], Dict[str, Any]]:
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
            book_value = self.extract_fmp_value(balance_sheet, 'totalStockholdersEquity')
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
            shares_outstanding = self.extract_fmp_value(income_statement, 'weightedAverageShsOut')
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
            normalized_weights = [w/total_weight for w in weights]
            weighted_sum = sum(v * w for v, w in zip(values, normalized_weights))
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
                result["current_price"] = self.extract_fmp_value(quote, 'price')
                result["pe_ratio"] = self.extract_fmp_value(quote, 'pe')
                result["market_cap"] = self.extract_fmp_value(quote, 'marketCap')
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
                intrinsic_value, iv_details = self.calculate_intrinsic_value(ticker, result["current_price"])
                result["intrinsic_value"] = intrinsic_value
                result["intrinsic_value_details"] = iv_details

        except Exception as e:
            result["errors"].append(f"Analysis error: {str(e)}")

        return result

# Initialize analyzer
analyzer = FMPStockAnalyzer(FMP_API_KEY)

# ==========================================
# 🔥 ОБНОВЛЕННАЯ EMAIL СИСТЕМА С REFERRAL
# ==========================================

def send_welcome_email_with_referral(email: str, license_key: str, full_name: str, referral_link: str = ""):
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
                <p>Share this link with friends and earn <strong>FREE months</strong> for every $24.99 payment:</p>

                <div style="background: rgba(255, 215, 0, 0.2); padding: 15px; border-radius: 8px; word-break: break-all; margin: 15px 0;">
                    <code style="color: #ffd700; font-size: 14px; font-weight: bold;">{referral_link}</code>
                </div>

                <p style="margin-bottom: 0;">
                    🎁 <strong>Each friend who joins = 1 FREE month for you!</strong><br>
                    💰 <strong>12 friends = FREE year of $7.99 data updates!</strong>
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
        .billing-info {{ background: rgba(255, 107, 53, 0.1); padding: 20px; border-radius: 10px; margin: 20px 0; border-left: 4px solid #ff6b35; }}
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
                <h4 style="color: #ff6b35; margin-top: 0;">💳 Monthly Data Updates - $7.99</h4>
                <p>Starting next month, $7.99 will be auto-billed on the 1st for:</p>
                <ul style="padding-left: 20px; margin: 10px 0;">
                    <li>🔄 Real-time market data</li>
                    <li>🔄 Server maintenance</li>
                    <li>🔄 New ProfitPal features</li>
                </ul>
                <p style="margin-bottom: 0;"><strong>💡 Use referrals to get FREE months and skip the $7.99 charge!</strong></p>
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

def send_referral_reward_email(referrer_email: str, new_balance: int, new_user_email: str):
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

# 🔥 ДОБАВЬ СЮДА DONATION EMAIL ФУНКЦИЮ:
def send_donation_thank_you_email(email: str, amount: float, donation_type: str):
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

        # Send email
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(GMAIL_EMAIL, GMAIL_PASSWORD)
            server.send_message(msg)

        print(f"✅ Donation thank you email sent to {email} (${amount}, {donation_type})")

    except Exception as e:
        print(f"❌ Failed to send donation email: {e}")

# ==========================================
# STATIC FILE ROUTES
# ==========================================

@app.get("/")
def serve_homepage():
    """Serve the main landing page"""
    return FileResponse('index.html')

# 🔥 НОВЫЙ ROUTE - REFERRAL REDIRECTS!
@app.get("/ref/{referral_code}")
def handle_referral_redirect(referral_code: str):
    """Handle referral links and redirect to main page with ref parameter"""
    try:
        print(f"🔗 Referral link clicked: {referral_code}")

        # Validate referral code format and existence
        if (referral_mgr.validate_referral_code_format(referral_code) and 
            referral_mgr.referral_code_exists(referral_code)):
            return RedirectResponse(url=f"/?ref={referral_code}", status_code=302)
        else:
            print(f"❌ Invalid referral code: {referral_code}")
            return RedirectResponse(url="/", status_code=302)

    except Exception as e:
        print(f"❌ Referral redirect error: {e}")
        return RedirectResponse(url="/", status_code=302)

@app.get("/analysis")
def serve_analysis():
    """Serve analysis page for payments"""
    return FileResponse('analysis.html')

@app.get("/fake-dashboard")
def serve_fake_dashboard():
    """Serve fake dashboard for free trial users"""
    return FileResponse('fake-dashboard.html')

@app.get("/success")
def serve_success():
    """Serve success page"""
    return FileResponse('success.html')

@app.get("/cancel")
def serve_cancel():
    """Serve cancel page"""
    return FileResponse('cancel.html')

@app.get("/terms-of-service")
def serve_terms():
    """Serve Terms of Service page"""
    return FileResponse('terms-of-service.html')

@app.get("/privacy-policy")
def serve_privacy():
    """Serve Privacy Policy page"""
    return FileResponse('privacy-policy.html')

@app.get("/refund-policy")
def serve_refund():
    """Serve Refund Policy page"""
    return FileResponse('refund-policy.html')

@app.get("/profitpal-styles.css")
def serve_css():
    """Serve ProfitPal CSS styles"""
    return FileResponse('profitpal-styles.css', media_type='text/css')

# ==========================================
# 🔥 ОБНОВЛЕННЫЕ AUTHENTICATION API ENDPOINTS
# ==========================================

@app.post('/validate-credentials')
async def check_credentials(request: Request):
    """🎯 ГЛАВНЫЙ API - Проверка email + license для подсветки имени + referral info"""
    try:
        body = await request.json()
        email = body.get('email', '').strip()
        license_key = body.get('license_key', '').strip().upper()

        if not email or not license_key:
            return JSONResponse(
                content={"show_name": False, "error": "Email and license key required"},
                status_code=400
            )

        # Используем auth_manager для валидации
        result = validate_user_credentials(email, license_key)

        if result['valid']:
            response_data = {
                "show_name": True, 
                "full_name": result['full_name'],
                "email": result['email'],
                "welcome_message": f"Welcome back, {result['full_name']}!"
            }

            # 🔥 ДОБАВЛЯЕМ REFERRAL INFO!
            referral_info = referral_mgr.get_user_referral_info(email)
            if referral_info:
                response_data.update({
                    "referral_code": referral_info['referral_code'],
                    "referral_link": referral_info['referral_link'],
                    "free_months_balance": referral_info['free_months_balance'],
                    "total_referrals": referral_info['total_referrals']
                })

            return JSONResponse(content=response_data)
        else:
            return JSONResponse(content={
                "show_name": False, 
                "error": result.get('error', 'Invalid credentials')
            })

    except Exception as e:
        print(f"❌ Credentials validation error: {e}")
        return JSONResponse(
            content={"show_name": False, "error": "Validation failed"},
            status_code=500
        )

@app.post('/api/check-admin-status')
async def check_admin_status(request: Request):
    """🎯 API для проверки админского статуса пользователя"""
    try:
        body = await request.json()
        email = body.get('email', '').strip().lower()
        fingerprint = body.get('fingerprint', '')

        # 👑 ПРОВЕРКА АДМИНСКОГО EMAIL ИЗ ENVIRONMENT VARIABLES
        admin_email = os.getenv('ADMIN_EMAIL', '').lower()
        is_admin = (email == admin_email)

        print(f"🎯 Admin status check: email={email}, admin_email={admin_email}, is_admin={is_admin}")

        return JSONResponse(
            content={
                "is_admin": is_admin,
                "admin_email": admin_email,
                "fingerprint": fingerprint,
                "status": "success"
            },
            status_code=200
        )

    except Exception as e:
        print(f"❌ Error in check_admin_status: {e}")
        return JSONResponse(
            content={"is_admin": False, "error": str(e)},
            status_code=500
        )

@app.post('/authenticate-user')
async def full_authentication(request: Request):
    """Полная аутентификация пользователя с созданием сессии"""
    try:
        body = await request.json()
        email = body.get('email', '').strip()
        license_key = body.get('license_key', '').strip().upper()
        full_name = body.get('full_name', '').strip()

        # Получаем IP и User Agent для безопасности
        ip_address = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")

        result = authenticate_user_login(
            email=email,
            license_key=license_key,
            full_name=full_name,
            ip_address=ip_address,
            user_agent=user_agent
        )

        if result['authenticated']:
            return JSONResponse(content={
                "success": True,
                "session_token": result['session_token'],
                "user": result['user'],
                "message": result['message']
            })
        else:
            return JSONResponse(
                content={"success": False, "error": result['error']},
                status_code=401
            )

    except Exception as e:
        print(f"❌ Authentication error: {e}")
        return JSONResponse(
            content={"success": False, "error": "Authentication failed"},
            status_code=500
        )

# ==========================================
# 🔥 ОБНОВЛЕННЫЕ STRIPE PAYMENT API С REFERRAL
# ==========================================

@app.get('/get-stripe-key')
def get_stripe_publishable_key():
    """Return Stripe publishable key for frontend"""
    return {"publishableKey": STRIPE_PUBLISHABLE_KEY}

@app.post('/create-checkout-session')
async def create_checkout_session(payment_request: PaymentRequest):
    """🔥 Create Stripe Checkout Session с REFERRAL поддержкой"""
    try:
        print(f"💳 Creating checkout for: {payment_request.full_name} ({payment_request.email})")
        print(f"🔗 Referral code: {payment_request.referral_code}")

        # Create Stripe Checkout session
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            customer_email=payment_request.email,
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': '💎 ProfitPal Pro Lifetime Access',
                        'description': 'Unlimited professional stock analysis + $7.99/month data updates',
                        'images': ['https://profitpal.org/logo.png'],
                    },
                    'unit_amount': 2499,  # $24.99 in cents
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f'{YOUR_DOMAIN}/success?session_id={{CHECKOUT_SESSION_ID}}',
            cancel_url=f'{YOUR_DOMAIN}/cancel',
            metadata={
                'full_name': payment_request.full_name,
                'email': payment_request.email,
                'referral_code': payment_request.referral_code or '',  # 🔥 СОХРАНЯЕМ REFERRAL!
                'product': 'profitpal_pro_lifetime',
                'version': '2.0'
            }
        )

        print(f"✅ Checkout session created: {checkout_session.id}")
        return {"checkout_url": checkout_session.url}

    except Exception as e:
        print(f"❌ Error creating checkout session: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to create checkout session: {str(e)}"
        )

@app.post('/stripe-webhook')
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks):
    """🔥 Handle Stripe webhook events + REFERRAL PROCESSING"""
    try:
        payload = await request.body()
        sig_header = request.headers.get('stripe-signature')

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
        except ValueError as e:
            print(f"❌ Invalid payload: {e}")
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError as e:
            print(f"❌ Invalid signature: {e}")
            raise HTTPException(status_code=400, detail="Invalid signature")

        print(f"🎯 Webhook received: {event['type']}")

        # Handle successful payment
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            email = session.get('customer_email')
            session_id = session.get('id')

            # Получаем данные из metadata
            metadata = session.get('metadata', {})
            full_name = metadata.get('full_name', 'ProfitPal User')
            referral_code = metadata.get('referral_code', '')

            if email and session_id and full_name:
                print(f"🎉 Payment completed for: {email}")
                print(f"🔗 Used referral code: {referral_code}")

                # 1. Создаем пользователя через auth_manager
                user_result = create_new_user(
                    email=email,
                    full_name=full_name,
                    stripe_customer_id=session.get('customer')
                )

                if user_result['success']:
                    license_key = user_result['license_key']
                    print(f"✅ User created: {full_name} ({email}) → {license_key}")

                    # 🔥 2. СОЗДАЕМ REFERRAL КОД ДЛЯ НОВОГО ПОЛЬЗОВАТЕЛЯ!
                    referral_result = referral_mgr.create_referral_for_user(email, YOUR_DOMAIN)
                    referral_link = ""
                    if referral_result['success']:
                        referral_link = referral_result['referral_link']
                        print(f"🔗 Referral created: {referral_result['referral_code']}")

                    # 🔥 3. ОБРАБАТЫВАЕМ ИСПОЛЬЗОВАННЫЙ REFERRAL КОД!
                    if referral_code and referral_mgr.referral_code_exists(referral_code):
                        signup_result = referral_mgr.process_referral_signup(referral_code, email, 24.99)
                        if signup_result['success']:
                            print(f"🎁 Referral processed! {signup_result['referrer_email']} earned free month")

                            # Отправляем email реферреру о награде
                            background_tasks.add_task(
                                send_referral_reward_email,
                                signup_result['referrer_email'],
                                signup_result['new_balance'],
                                email
                            )

                    # 4. Отправляем welcome email новому пользователю с referral ссылкой
                    background_tasks.add_task(
                        send_welcome_email_with_referral, 
                        email, 
                        license_key, 
                        full_name,
                        referral_link
                    )

                else:
                    print(f"❌ Failed to create user: {user_result.get('error')}")
            else:
                print(f"❌ Missing required data in webhook: email={email}, name={full_name}")

        return JSONResponse(content={"status": "success"}, status_code=200)

    except Exception as e:
        print(f"❌ Webhook error: {e}")
        raise HTTPException(status_code=500, detail="Webhook processing failed")

# ==========================================
# 🔥 НОВЫЕ REFERRAL API ENDPOINTS
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
            status_code=500
        )

@app.get('/api/referral-link/{email}')
async def get_user_referral_link(email: str):
    """Получить referral ссылку пользователя"""
    try:
        referral_info = referral_mgr.get_user_referral_info(email)
        if referral_info:
            return JSONResponse(content={
                'referral_link': referral_info['referral_link'],
                'referral_code': referral_info['referral_code'],
                'free_months_balance': referral_info['free_months_balance'],
                'total_referrals': referral_info['total_referrals']
            })
        else:
            return JSONResponse(
                content={'error': 'No referral info found'},
                status_code=404
            )
    except Exception as e:
        print(f"❌ Error getting referral link: {e}")
        return JSONResponse(
            content={'error': 'Failed to get referral link'},
            status_code=500
        )

@app.post('/api/monthly-billing/{email}')
async def process_monthly_billing(email: str):
    """🔥 Обработать месячный billing с учетом referral free months"""
    try:
        billing_result = referral_mgr.check_and_use_free_month(email)

        if billing_result['should_charge']:
            charge_amount = billing_result['charge_amount']
            print(f"💳 Charging ${charge_amount} for {email}")
            # TODO: Stripe subscription billing integration
        else:
            print(f"🎁 Free month used for {email}. {billing_result['free_months_remaining']} remaining")

        return JSONResponse(content=billing_result)

    except Exception as e:
        print(f"❌ Monthly billing error: {e}")
        return JSONResponse(
            content={'error': 'Monthly billing failed'},
            status_code=500
        )

# 🔍 ДОБАВИТЬ СЮДА FREE TRIAL ENDPOINTS:
@app.post("/api/check-free-trial")
async def check_free_trial(request: FreeTrialRequest):
    """Проверка лимита бесплатных анализов по fingerprint"""
    try:
        print(f"🔍 Checking free trial for fingerprint: {request.fingerprint[:10]}...")

        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        # Найти запись по fingerprint
        cursor.execute('''
            SELECT analyses_used, max_analyses 
            FROM free_trials 
            WHERE fingerprint = ?
        ''', (request.fingerprint,))

        result = cursor.fetchone()
        conn.close()

        if result:
            analyses_used, max_analyses = result
            remaining = max_analyses - analyses_used
            allowed = remaining > 0

            print(f"📊 Existing user: {analyses_used}/{max_analyses} used, remaining: {remaining}")
        else:
            # Новый пользователь
            analyses_used = 0
            max_analyses = 5
            remaining = 5
            allowed = True

            print(f"🆕 New user: {remaining} analyses available")

        return JSONResponse(content={
            'allowed': allowed,
            'used': analyses_used,
            'remaining': remaining,
            'max_analyses': max_analyses
        })

    except Exception as e:
        print(f"❌ Error checking free trial: {e}")
        return JSONResponse(
            content={'error': f'Free trial check failed: {str(e)}'},
            status_code=500
        )

@app.post("/api/record-free-trial")
async def record_free_trial(request: FreeTrialRecordRequest):
    """Запись использования бесплатного анализа"""
    try:
        print(f"📝 Recording free trial usage: {request.fingerprint[:10]}... ticker: {request.ticker}")

        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        # Проверить существующую запись
        cursor.execute('''
            SELECT analyses_used, max_analyses 
            FROM free_trials 
            WHERE fingerprint = ?
        ''', (request.fingerprint,))

        result = cursor.fetchone()

        if result:
            # Обновить существующую запись
            analyses_used, max_analyses = result
            new_count = analyses_used + 1

            cursor.execute('''
                UPDATE free_trials 
                SET analyses_used = ?, last_used = CURRENT_TIMESTAMP
                WHERE fingerprint = ?
            ''', (new_count, request.fingerprint))

            print(f"📈 Updated existing user: {new_count}/{max_analyses} used")

        else:
            # Создать новую запись
            cursor.execute('''
                INSERT INTO free_trials (fingerprint, analyses_used, max_analyses)
                VALUES (?, 1, 5)
            ''', (request.fingerprint,))

            new_count = 1
            max_analyses = 5
            print(f"🆕 Created new user: {new_count}/{max_analyses} used")

        conn.commit()
        conn.close()

        remaining = max_analyses - new_count

        return JSONResponse(content={
            'success': True,
            'analyses_used': new_count,
            'remaining': remaining,
            'ticker': request.ticker
        })

    except Exception as e:
        print(f"❌ Error recording free trial: {e}")
        return JSONResponse(
            content={'error': f'Free trial recording failed: {str(e)}'},
            status_code=500
        )

# 🔥 ДОБАВИТЬ СЮДА НОВЫЙ ENDPOINT:
@app.post("/api/process-donation")
async def process_donation(request: DonationRequest):
    """💎 Обработка donation платежей через Stripe"""
    try:
        print(f"💝 Processing donation: ${request.amount} ({request.type}) from {request.email}")

        # Найти пользователя в базе
        auth_user = auth_mgr.get_user_by_email(request.email)
        if not auth_user:
            raise Exception("User not found")

        # Создать Stripe payment intent для donation
        payment_intent = stripe.PaymentIntent.create(
            amount=int(request.amount * 100),  # Конвертируем в центы
            currency='usd',
            customer=auth_user['stripe_customer_id'],
            payment_method=auth_user.get('default_payment_method'),
            confirm=True,
            description=f"ProfitPal Boost Development - {request.type}",
            metadata={
                'type': 'donation',
                'donation_type': request.type,
                'user_email': request.email
            }
        )

        # Отправить персонализированный thank you email
        await send_donation_thank_you_email(request.email, request.amount, request.type)

        print(f"✅ Donation processed successfully: ${request.amount}")

        return JSONResponse(content={
            'success': True,
            'amount': request.amount,
            'message': 'Thank you for boosting ProfitPal development!'
        })

    except Exception as e:
        print(f"❌ Donation processing error: {e}")
        return JSONResponse(
            content={'error': f'Donation failed: {str(e)}'},
            status_code=500
        )

# ==========================================
# STOCK ANALYSIS API ENDPOINTS (UNCHANGED)
# ==========================================

@app.post("/analyze", response_model=AnalysisResponse)
async def analyze_stock(request: AnalysisRequest):
    """Analyze stock with license validation"""
    try:
        print(f"🔍 Analysis request for {request.ticker} with license: {request.license_key}")

        # License validation for PRO features
        if request.license_key != "FREE" and request.license_key:
            # Validate license through auth_manager
            pass

        # Get stock data
        print(f"📊 Fetching data for {request.ticker.upper()}")
        stock_data = analyzer.get_complete_stock_data(request.ticker.upper())

        if not stock_data["current_price"]:
            print(f"❌ No data found for {request.ticker}")
            raise HTTPException(
                status_code=404, 
                detail=f"Stock data not found for {request.ticker}"
            )

        # Extract data
        current_price = stock_data["current_price"]
        pe_ratio = stock_data["pe_ratio"]
        market_cap = stock_data["market_cap"]
        debt_ratio = stock_data["debt_ratio"]
        intrinsic_value = stock_data["intrinsic_value"]

        # Calculate valuation gap
        valuation_gap = None
        if intrinsic_value and current_price:
            valuation_gap = ((intrinsic_value - current_price) / current_price) * 100

        # Analysis logic
        verdict_factors = []

        # P/E Analysis
        if pe_ratio:
            if request.pe_min <= pe_ratio <= request.pe_max:
                verdict_factors.append("✅ P/E PASS")
            else:
                verdict_factors.append("❌ P/E FAIL")

        # Debt Analysis
        if debt_ratio:
            if debt_ratio <= request.debt_max:
                verdict_factors.append("✅ DEBT PASS")
            else:
                verdict_factors.append("❌ DEBT FAIL")

        # Valuation Analysis
        if valuation_gap:
            if valuation_gap > 20:
                verdict_factors.append("💎 UNDERVALUED")
            elif valuation_gap < -20:
                verdict_factors.append("⚠️ OVERVALUED")
            else:
                verdict_factors.append("📊 FAIRLY VALUED")

        # Final verdict
        passed_filters = sum(1 for factor in verdict_factors if "✅" in factor)
        total_filters = sum(1 for factor in verdict_factors if ("✅" in factor or "❌" in factor))

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
                "verdict_factors": verdict_factors,
                "filters_passed": f"{passed_filters}/{total_filters}",
                "errors": stock_data.get("errors", []),
                "license_used": request.license_key,
                "educational_note": "This analysis is for educational purposes only. Not financial advice."
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Analysis failed for {request.ticker}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

# ==========================================
# 🔥 ОБНОВЛЕННЫЕ ADMIN ENDPOINTS С REFERRAL
# ==========================================

@app.get("/admin/stats")
async def get_admin_stats():
    """🔥 Get comprehensive system statistics + REFERRAL stats"""
    try:
        auth_stats = get_auth_stats()
        referral_stats = referral_mgr.get_all_referral_stats()  # 🔥 НОВЫЙ!

        return JSONResponse(content={
            "system": {
                "version": "2.0.0",
                "environment": "production" if "profitpal.org" in YOUR_DOMAIN else "development",
                "domain": YOUR_DOMAIN
            },
            "auth": auth_stats,
            "referrals": referral_stats,  # 🔥 НОВЫЙ!
            "api": {
                "fmp_key_status": "configured" if len(FMP_API_KEY) > 10 else "missing",
                "stripe_status": "configured" if len(STRIPE_SECRET_KEY) > 10 else "missing",
                "email_status": "configured" if GMAIL_PASSWORD else "missing"
            },
            "generated_at": datetime.now().isoformat()
        })

    except Exception as e:
        print(f"❌ Admin stats error: {e}")
        return JSONResponse(
            content={"error": "Failed to get stats"},
            status_code=500
        )

@app.get("/health")
def health_check():
    """🔥 System health check + REFERRAL system"""
    return {
        "status": "healthy",
        "version": "2.0.0",
        "features": [
            "auth_manager", 
            "stripe_payments", 
            "email_notifications", 
            "stock_analysis",
            "referral_system",  # 🔥 НОВЫЙ!
            "environment_variables"
        ],
        "endpoints": [
            "/", 
            "/analysis", 
            "/fake-dashboard", 
            "/validate-credentials",
            "/create-checkout-session",
            "/stripe-webhook",
            "/analyze",
            "/api/referral-stats/{email}",  # 🔥 НОВЫЙ!
            "/api/referral-link/{email}",   # 🔥 НОВЫЙ!
            "/ref/{referral_code}"          # 🔥 НОВЫЙ!
        ],
        "timestamp": datetime.now().isoformat()
    }

# ==========================================
# APPLICATION STARTUP
# ==========================================

if __name__ == "__main__":
    import uvicorn

    # Создаем таблицу при запуске
    create_free_trial_table()

    print("\n" + "="*60)
    print("🚀🚀🚀 PROFITPAL PRO SERVER v2.0 STARTING 🚀🚀🚀")
    print("="*60)
    print("✅ Auth Manager: Integrated")
    print("✅ Referral Manager: Integrated")  # 🔥 НОВЫЙ!
    print("✅ Environment Variables: Configured") 
    print("✅ Stripe Payments: Ready")
    print("✅ Email Notifications: Ready")
    print("✅ Stock Analysis: FMP API Connected")
    print("✅ Database: Auth + Referral + Free Trial Management")  # 🔥 ОБНОВЛЕН!
    print("💎 Ready for Production with Referral System! 💎")
    print("="*60 + "\n")

    uvicorn.run(app, host="0.0.0.0", port=8000)

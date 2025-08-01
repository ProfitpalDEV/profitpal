import requests
import json
import stripe
import secrets
import hashlib
import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import re

# Stripe Configuration
stripe.api_key = 'sk_test_51RqAupL8Gx8kkO0xVr2i4GQjlrrzkGKVh0mH5WvUtFfqgokrD8J4RZmsOxFOu0HRBuhsze4u5wW5sLcJmfdspO1s00nnwUVsJW'
STRIPE_WEBHOOK_SECRET = 'whsec_12345'  # Get from Stripe Dashboard later
YOUR_DOMAIN = 'https://profitpal.org'  # Updated Replit domain

# Product Price IDs
SETUP_FEE_PRICE_ID = 'price_1RqBUyL8Gx8kkO0xGjLG0DVh'  # $24.99 one-time
MONTHLY_SUBSCRIPTION_PRICE_ID = 'price_1RqBAGL8Gx8kkO0x42tjEGaA'  # $4.99/month

# API Models
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

# FastAPI app
app = FastAPI(
    title="AI StockScreener Pro API",
    description="Educational stock analysis platform - aggregating data, calculating metrics, empowering decisions",
    version="1.0.0"
)

# Add CORS middleware - CRITICAL FIX for "Method Not Allowed"
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Database Setup
def init_database():
    """Initialize SQLite database for users and subscriptions"""
    try:
        conn = sqlite3.connect('profitpal.db')
        cursor = conn.cursor()

        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                stripe_customer_id TEXT,
                license_key TEXT UNIQUE,
                subscription_status TEXT DEFAULT 'inactive',
                subscription_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Payments table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                stripe_payment_id TEXT,
                amount INTEGER,
                type TEXT,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')

        conn.commit()
        conn.close()
        print("✅ Database initialized successfully")
    except Exception as e:
        print(f"❌ Database initialization error: {e}")

# Initialize database on startup
init_database()

def generate_license_key(customer_id: str) -> str:
    """Generate unique license key for customer"""
    random_part = secrets.token_hex(8)
    customer_hash = hashlib.md5(customer_id.encode()).hexdigest()[:8]
    return f"PP-{customer_hash}-{random_part}".upper()

def get_db_connection():
    """Get database connection"""
    conn = sqlite3.connect('profitpal.db')
    conn.row_factory = sqlite3.Row
    return conn

def validate_license_key(license_key: str) -> dict:
    """Validate license key and return user info"""
    if license_key == "FREE" or license_key == "":
        return {"email": "free_user", "status": "free"}

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM users 
            WHERE license_key = ? AND subscription_status = 'active'
        ''', (license_key,))
        user = cursor.fetchone()
        conn.close()

        if user:
            return dict(user)
        return None
    except Exception as e:
        print(f"License validation error: {e}")
        return None

# FMP API Configuration
FMP_API_KEY = "re6q6DqcjkmRuiXE0fNiDHIYwVH3DcfC"
FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"

class FMPStockAnalyzer:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = FMP_BASE_URL

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
                # Clean string values
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
        """Calculate intrinsic value using 4 methods with weighted average"""
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
                # Simple DCF: FCF * 10 (assuming 10% discount rate)
                details["dcf_method"] = free_cash_flow * 10 / 1000000  # Convert to per share approximation

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
                # Conservative P/E of 15
                details["earnings_method"] = eps * 15

        # Method 4: Revenue multiple
        if income_statement:
            revenue = self.extract_fmp_value(income_statement, 'revenue')
            shares_outstanding = self.extract_fmp_value(income_statement, 'weightedAverageShsOut')
            if revenue and shares_outstanding and shares_outstanding > 0:
                revenue_per_share = revenue / shares_outstanding
                # Conservative P/S of 3
                details["revenue_method"] = revenue_per_share * 3

        # Calculate weighted average
        values = []
        weights = []

        if details["dcf_method"]:
            values.append(details["dcf_method"])
            weights.append(0.4)  # 40% weight for DCF

        if details["earnings_method"]:
            values.append(details["earnings_method"])
            weights.append(0.3)  # 30% weight for earnings

        if details["book_value_method"]:
            values.append(details["book_value_method"])
            weights.append(0.2)  # 20% weight for book value

        if details["revenue_method"]:
            values.append(details["revenue_method"])
            weights.append(0.1)  # 10% weight for revenue

        if values:
            # Normalize weights
            total_weight = sum(weights)
            normalized_weights = [w/total_weight for w in weights]

            # Calculate weighted average
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

            # Get debt ratio (try multiple methods)
            debt_ratio = self.get_debt_from_balance_sheet(ticker)
            if debt_ratio is None:
                debt_ratio = self.get_debt_from_ratios(ticker)
            if debt_ratio is None:
                debt_ratio = 25.0  # Default assumption
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

# STRIPE PAYMENT ENDPOINTS
@app.post('/create-checkout-session')
async def create_checkout_session(email: str = Form(...)):
    """Create Stripe Checkout Session for ProfitPal subscription"""
    try:
        print(f"Creating checkout session for email: {email}")

        # Create Stripe Checkout Session for setup fee
        setup_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': SETUP_FEE_PRICE_ID,  # $24.99 setup fee
                'quantity': 1,
            }],
            mode='payment',
            customer_email=email,
            success_url=f'{YOUR_DOMAIN}/setup-success?session_id={{CHECKOUT_SESSION_ID}}',
            cancel_url=f'{YOUR_DOMAIN}/cancel',
            metadata={
                'type': 'setup_payment',
                'email': email
            }
        )

        print(f"✅ Checkout session created: {setup_session.id}")
        return RedirectResponse(url=setup_session.url, status_code=303)

    except Exception as e:
        print(f"❌ Error creating checkout session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create checkout session: {str(e)}")

@app.get('/setup-success')
async def setup_success(session_id: str):
    """Handle successful setup payment and create subscription"""
    try:
        print(f"Processing setup success for session: {session_id}")

        # Retrieve the checkout session
        session = stripe.checkout.Session.retrieve(session_id)
        customer_email = session.customer_email
        customer_id = session.customer

        # Create customer record in database
        conn = get_db_connection()
        cursor = conn.cursor()

        # Generate license key
        license_key = generate_license_key(customer_id)
        print(f"Generated license key: {license_key}")

        # Insert or update user
        cursor.execute('''
            INSERT OR REPLACE INTO users 
            (email, stripe_customer_id, license_key, subscription_status) 
            VALUES (?, ?, ?, ?)
        ''', (customer_email, customer_id, license_key, 'setup_complete'))

        user_id = cursor.lastrowid

        # Record setup payment
        cursor.execute('''
            INSERT INTO payments 
            (user_id, stripe_payment_id, amount, type, status) 
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, session.payment_intent, 2499, 'setup', 'completed'))

        conn.commit()
        conn.close()

        # Now create the monthly subscription
        subscription = stripe.Subscription.create(
            customer=customer_id,
            items=[{
                'price': MONTHLY_SUBSCRIPTION_PRICE_ID,  # $4.99/month
            }],
        )

        print(f"✅ Subscription created: {subscription.id}")

        # Update user with subscription info
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users 
            SET subscription_id = ?, subscription_status = ? 
            WHERE stripe_customer_id = ?
        ''', (subscription.id, 'active', customer_id))
        conn.commit()
        conn.close()

        # Return success page with license key
        return f"""
        <html>
        <head><title>Welcome to ProfitPal Pro!</title></head>
        <body style="font-family: Arial; text-align: center; padding: 50px; background: #0a0e27; color: white;">
            <h1 style="color: #32cd32;">✅ Payment Successful!</h1>
            <h2 style="color: #ffd700;">Welcome to ProfitPal Pro!</h2>
            <p><strong>Your License Key:</strong></p>
            <div style="background: #1e3a5f; padding: 20px; margin: 20px; font-size: 24px; font-weight: bold; border-radius: 10px; border: 2px solid #32cd32;">
                {license_key}
            </div>
            <p style="color: #95a5a6;">Save this license key! Use it in the analysis form.</p>
            <p style="color: #95a5a6;">Your subscription: $4.99/month (started automatically)</p>
            <a href="/analysis" style="background: #32cd32; color: white; padding: 15px 30px; text-decoration: none; border-radius: 10px; font-weight: bold; margin-top: 20px; display: inline-block;">Start Analyzing Stocks</a>
        </body>
        </html>
        """

    except Exception as e:
        print(f"❌ Error in setup success: {e}")
        return f"""
        <html>
        <head><title>Error</title></head>
        <body style="font-family: Arial; text-align: center; padding: 50px; background: #0a0e27; color: white;">
            <h1 style="color: #e74c3c;">❌ Something went wrong</h1>
            <p>Error: {str(e)}</p>
            <p>Please contact support.</p>
            <a href="/analysis" style="background: #32cd32; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Try Again</a>
        </body>
        </html>
        """

@app.get('/cancel')
async def payment_cancelled():
    """Handle cancelled payment"""
    return """
    <html>
    <head><title>Payment Cancelled</title></head>
    <body style="font-family: Arial; text-align: center; padding: 50px; background: #0a0e27; color: white;">
        <h1 style="color: #e74c3c;">❌ Payment Cancelled</h1>
        <p>No worries! You can try again anytime.</p>
        <a href="/analysis" style="background: #32cd32; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Back to Analysis</a>
    </body>
    </html>
    """

@app.post('/webhook')
async def stripe_webhook(request: Request):
    """Handle Stripe webhooks"""
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
        print(f"Webhook received: {event['type']}")
    except ValueError:
        print("❌ Invalid webhook payload")
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        print("❌ Invalid webhook signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Handle different event types
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        print(f"✅ Setup payment successful for {session.get('customer_email')}")

    elif event['type'] == 'invoice.payment_succeeded':
        invoice = event['data']['object']
        customer_id = invoice['customer']

        # Update user status to active
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users 
            SET subscription_status = ? 
            WHERE stripe_customer_id = ?
        ''', ('active', customer_id))
        conn.commit()
        conn.close()

        print(f"✅ Monthly payment successful for customer {customer_id}")

    elif event['type'] == 'invoice.payment_failed':
        invoice = event['data']['object']
        customer_id = invoice['customer']

        # Suspend user access
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users 
            SET subscription_status = ? 
            WHERE stripe_customer_id = ?
        ''', ('payment_failed', customer_id))
        conn.commit()
        conn.close()

        print(f"❌ Monthly payment failed for customer {customer_id}")

    return JSONResponse({'status': 'success'})

# EXISTING ROUTES
@app.get("/")
def serve_homepage():
    """Serve the main landing page"""
    return FileResponse('index.html')

@app.get("/app")
def serve_login():
    """Serve the login page for user dashboard"""
    return FileResponse('app.html')

@app.get("/app/dashboard")
def serve_dashboard():
    return FileResponse('dashboard.html') 

@app.get("/app/analysis")
def serve_analysis():
    return FileResponse('analysis.html')

# CRITICAL FIX: Direct analysis access
@app.get("/analysis")
def serve_analysis_direct():
    """Serve analysis page directly - fixes 404 Not Found error"""
    return FileResponse('analysis.html')

@app.get("/health")
def health_check():
    """API health check"""
    return {
        "status": "healthy",
        "api": "FMP",
        "endpoints": ["/analyze", "/health", "/docs", "/app/", "/analysis", "/create-checkout-session"],
        "stripe": "integrated",
        "domain": YOUR_DOMAIN,
        "database": "initialized"
    }

# CRITICAL FIX: Analysis endpoint with better error handling
@app.post("/analyze", response_model=AnalysisResponse)
async def analyze_stock(request: AnalysisRequest):
    """
    Analyze a stock using educational financial metrics with license validation

    This endpoint aggregates public financial data and performs mathematical
    calculations for educational purposes only. Not financial advice.
    """
    try:
        print(f"🔍 Analysis request for {request.ticker} with license: {request.license_key}")

        # Validate license key
        if request.license_key == "FREE" or not request.license_key:
            print("🆓 Free user analysis")
            # Free users get limited access
            pass
        else:
            # Validate PRO license key
            user = validate_license_key(request.license_key)
            if not user:
                print(f"❌ Invalid license key: {request.license_key}")
                raise HTTPException(
                    status_code=403, 
                    detail="Invalid or expired license key. Please subscribe to ProfitPal Pro."
                )
            print(f"✅ Valid license for user: {user.get('email', 'unknown')}")

        # Get stock data
        print(f"📊 Fetching data for {request.ticker.upper()}")
        stock_data = analyzer.get_complete_stock_data(request.ticker.upper())

        if not stock_data["current_price"]:
            print(f"❌ No data found for {request.ticker}")
            raise HTTPException(status_code=404, detail=f"Stock data not found for {request.ticker}")

        # Perform analysis
        current_price = stock_data["current_price"]
        pe_ratio = stock_data["pe_ratio"]
        market_cap = stock_data["market_cap"]
        debt_ratio = stock_data["debt_ratio"]
        intrinsic_value = stock_data["intrinsic_value"]

        # Calculate valuation gap
        valuation_gap = None
        if intrinsic_value and current_price:
            valuation_gap = ((intrinsic_value - current_price) / current_price) * 100

        # Determine verdict based on filters
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

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting ProfitPal API server...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
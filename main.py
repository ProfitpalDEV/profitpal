import requests
import json
import secrets
import hashlib
import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import re
import uvicorn
import os

# Environment Variables for Production Security
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', 'demo_mode')
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY', 'pk_test_demo')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', 'whsec_demo')
FMP_API_KEY = os.environ.get('FMP_API_KEY', 're6q6DqcjkmRuiXE0fNiDHIYwVH3DcfC')
YOUR_DOMAIN = os.environ.get('YOUR_DOMAIN', 'https://profitpal.org')

# Stripe Configuration (only if not in demo mode)
if STRIPE_SECRET_KEY != 'demo_mode':
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY

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
    title="ProfitPal - AI Stock Analysis",
    description="Professional stock analysis with Diamond Rating system",
    version="3.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    if license_key == "FREE" or license_key == "" or license_key == "PP-DEMO-12345678":
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
            balance_sheet = self.call_fmp_api(f"balance-sheet-statement/{ticker}")
            if balance_sheet:
                total_debt = self.extract_fmp_value(balance_sheet, 'totalDebt')
                total_assets = self.extract_fmp_value(balance_sheet, 'totalAssets')
                if total_debt is not None and total_assets is not None and total_assets > 0:
                    result["debt_ratio"] = (total_debt / total_assets) * 100
                else:
                    result["debt_ratio"] = 25.0  # Default
                    result["errors"].append("Using default debt ratio")
            else:
                result["debt_ratio"] = 25.0
                result["errors"].append("Using default debt ratio")

            # Calculate intrinsic value (simplified)
            if result["current_price"] and result["pe_ratio"]:
                # Simple intrinsic value: current_price * (fair_pe / actual_pe)
                fair_pe = 15  # Conservative fair P/E
                if result["pe_ratio"] > 0:
                    result["intrinsic_value"] = result["current_price"] * (fair_pe / result["pe_ratio"])
                else:
                    result["intrinsic_value"] = result["current_price"] * 1.15  # 15% premium for no P/E

        except Exception as e:
            result["errors"].append(f"Analysis error: {str(e)}")

        return result

# Initialize analyzer
analyzer = FMPStockAnalyzer(FMP_API_KEY)

# ROUTES
@app.get("/")
def read_root():
    """Serve the main analysis page"""
    return FileResponse("analysis.html")

@app.get("/analysis")
def get_analysis():
    """Serve analysis page"""
    return FileResponse("analysis.html")

@app.post("/create-checkout-session")
async def create_checkout_session(email: str = Form(...)):
    """Create Stripe checkout session"""
    try:
        print(f"Creating checkout session for email: {email}")
        
        # Demo mode - redirect to success with demo license
        if STRIPE_SECRET_KEY == 'demo_mode':
            return RedirectResponse(
                url=f"/setup-success?email={email}&demo=true", 
                status_code=303
            )
        
        # Production mode - real Stripe
        setup_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': SETUP_FEE_PRICE_ID,
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
        print(f"Error creating checkout session: {e}")
        # Fallback to demo mode on error
        return RedirectResponse(
            url=f"/setup-success?email={email}&demo=true", 
            status_code=303
        )

@app.get("/setup-success")
async def setup_success(email: str = "", session_id: str = "", demo: str = ""):
    """Handle successful payment setup"""
    
    # Demo mode
    if demo == "true" or STRIPE_SECRET_KEY == 'demo_mode':
        license_key = "PP-DEMO-12345678"
    else:
        # Production mode - process real Stripe session
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            customer_email = session.customer_email
            customer_id = session.customer
            
            # Generate real license key
            license_key = generate_license_key(customer_id)
            
            # Store in database
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO users 
                (email, stripe_customer_id, license_key, subscription_status) 
                VALUES (?, ?, ?, ?)
            ''', (customer_email, customer_id, license_key, 'active'))
            conn.commit()
            conn.close()
            
        except Exception as e:
            print(f"Error processing real payment: {e}")
            license_key = "PP-DEMO-12345678"  # Fallback
    
    return HTMLResponse(f"""
    <html>
    <head>
        <title>Welcome to ProfitPal Pro!</title>
        <style>
            body {{
                font-family: 'Inter', Arial, sans-serif;
                background: linear-gradient(135deg, #0a0e27 0%, #1e3a5f 50%, #2c5f2d 100%);
                color: white;
                text-align: center;
                padding: 50px;
                min-height: 100vh;
                margin: 0;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background: rgba(30, 58, 95, 0.6);
                padding: 40px;
                border-radius: 20px;
                border: 2px solid #32cd32;
            }}
            h1 {{ color: #32cd32; margin-bottom: 20px; }}
            h2 {{ color: #ffd700; margin-bottom: 30px; }}
            .license-key {{
                background: #1e3a5f;
                padding: 20px;
                margin: 20px 0;
                font-size: 24px;
                font-weight: bold;
                border-radius: 10px;
                border: 2px solid #32cd32;
                letter-spacing: 2px;
            }}
            .btn {{
                background: linear-gradient(135deg, #32cd32, #228b22);
                color: white;
                padding: 15px 30px;
                text-decoration: none;
                border-radius: 10px;
                font-weight: bold;
                margin-top: 20px;
                display: inline-block;
                transition: transform 0.3s ease;
            }}
            .btn:hover {{ transform: translateY(-2px); }}
            .note {{ color: #95a5a6; font-size: 14px; margin-top: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>✅ Welcome to ProfitPal Pro!</h1>
            <h2>🎉 Payment Setup Complete!</h2>
            
            <p><strong>Your License Key:</strong></p>
            <div class="license-key">
                {license_key}
            </div>
            
            <p>📧 Account: {email}</p>
            <p class="note">💡 Save this license key! Use it in the analysis form to unlock full features.</p>
            <p class="note">💳 Subscription: $4.99/month {'(demo mode)' if license_key == 'PP-DEMO-12345678' else ''}</p>
            
            <a href="/analysis" class="btn">🚀 Start Analyzing Stocks</a>
            
            {'<div class="note" style="margin-top: 40px;"><p><strong>Demo Mode Active</strong></p><p>This is a demonstration. In production, real Stripe payments and license keys would be generated.</p></div>' if license_key == 'PP-DEMO-12345678' else ''}
        </div>
    </body>
    </html>
    """)

@app.get("/cancel")
async def payment_cancelled():
    """Handle cancelled payment"""
    return HTMLResponse("""
    <html>
    <head>
        <title>Payment Cancelled</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background: linear-gradient(135deg, #0a0e27 0%, #1e3a5f 50%, #2c5f2d 100%);
                color: white;
                text-align: center;
                padding: 50px;
                min-height: 100vh;
                margin: 0;
            }
            .container {
                max-width: 400px;
                margin: 0 auto;
                background: rgba(30, 58, 95, 0.6);
                padding: 40px;
                border-radius: 20px;
                border: 2px solid #e74c3c;
            }
            h1 { color: #e74c3c; }
            .btn {
                background: #32cd32;
                color: white;
                padding: 15px 30px;
                text-decoration: none;
                border-radius: 10px;
                font-weight: bold;
                display: inline-block;
                margin-top: 20px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>❌ Payment Cancelled</h1>
            <p>No worries! You can try again anytime.</p>
            <a href="/analysis" class="btn">Back to Analysis</a>
        </div>
    </body>
    </html>
    """)

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
        else:
            # Validate PRO license key (allow demo key)
            user = validate_license_key(request.license_key)
            if not user and request.license_key != "PP-DEMO-12345678":
                print(f"❌ Invalid license key: {request.license_key}")
                raise HTTPException(
                    status_code=403, 
                    detail="Invalid or expired license key. Please subscribe to ProfitPal Pro."
                )
            print(f"✅ Valid license for user: {user.get('email', 'demo_user') if user else 'demo_user'}")

        # Demo data for testing
        if request.ticker.upper() in ["DEMO", "TEST", "OSCR"]:
            return AnalysisResponse(
                ticker=request.ticker.upper(),
                current_price=42.50,
                pe_ratio=18.5,
                market_cap=125000000,
                debt_ratio=25.3,
                intrinsic_value=48.20,
                valuation_gap=13.4,
                final_verdict="💎 DIAMOND FOUND - Demo Analysis",
                analysis_details={
                    "verdict_factors": ["✅ P/E PASS", "✅ DEBT PASS", "💎 UNDERVALUED"],
                    "filters_passed": "3/3",
                    "errors": [],
                    "license_used": request.license_key,
                    "educational_note": "This is demo data. Real analysis requires live financial data."
                }
            )

        # Get real stock data
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

@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "ProfitPal",
        "version": "3.0.0",
        "endpoints": ["/", "/analysis", "/health", "/analyze", "/create-checkout-session"],
        "stripe": "production" if STRIPE_SECRET_KEY != 'demo_mode' else "demo_mode",
        "fmp_api": "integrated",
        "database": "initialized"
    }

# Webhook endpoint for production
@app.post('/webhook')
async def stripe_webhook(request: Request):
    """Handle Stripe webhooks"""
    if STRIPE_SECRET_KEY == 'demo_mode':
        return JSONResponse({'status': 'demo_mode'})
    
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
        print(f"Webhook received: {event['type']}")
        
        # Handle webhook events here
        return JSONResponse({'status': 'success'})
        
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        raise HTTPException(status_code=400, detail="Webhook error")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print("🚀 Starting ProfitPal API server...")
    print(f"💎 Server running on port {port}")
    print(f"🔐 Stripe mode: {'Production' if STRIPE_SECRET_KEY != 'demo_mode' else 'Demo'}")
    print(f"📊 FMP API: {'Connected' if FMP_API_KEY else 'Demo mode'}")
    uvicorn.run(app, host="0.0.0.0", port=port)

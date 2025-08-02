from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os

# FastAPI app
app = FastAPI(
    title="ProfitPal - AI Stock Analysis",
    description="Professional stock analysis with Diamond Rating system",
    version="2.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

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
        
        # For now, redirect to a placeholder success page
        # In production, this would create a real Stripe session
        return RedirectResponse(
            url=f"/setup-success?email={email}", 
            status_code=303
        )
    except Exception as e:
        print(f"Error creating checkout session: {e}")
        raise HTTPException(status_code=500, detail="Payment system temporarily unavailable")

@app.get("/setup-success")
async def setup_success(email: str = ""):
    """Handle successful payment setup"""
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
                PP-DEMO-12345678
            </div>
            
            <p>📧 Account: {email}</p>
            <p class="note">💡 Save this license key! Use it in the analysis form to unlock full features.</p>
            <p class="note">💳 Subscription: $4.99/month (demo mode)</p>
            
            <a href="/analysis" class="btn">🚀 Start Analyzing Stocks</a>
            
            <div class="note" style="margin-top: 40px;">
                <p><strong>Demo Mode Active</strong></p>
                <p>This is a demonstration. In production, real Stripe payments and license keys would be generated.</p>
            </div>
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

@app.post("/analyze")
async def analyze_stock():
    """Placeholder analyze endpoint"""
    return {
        "ticker": "DEMO",
        "current_price": 42.50,
        "pe_ratio": 18.5,
        "market_cap": 125000000,
        "debt_ratio": 25.3,
        "intrinsic_value": 48.20,
        "valuation_gap": 13.4,
        "final_verdict": "💎 DIAMOND FOUND - Demo Analysis",
        "analysis_details": {
            "verdict_factors": ["✅ P/E PASS", "✅ DEBT PASS", "💎 UNDERVALUED"],
            "filters_passed": "3/3",
            "errors": [],
            "educational_note": "This is demo data. Real analysis requires live financial data."
        }
    }

@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "ProfitPal",
        "version": "2.0.0",
        "endpoints": ["/", "/analysis", "/health"],
        "stripe": "demo_mode"
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print("🚀 Starting ProfitPal API server...")
    print(f"💎 Server running on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)

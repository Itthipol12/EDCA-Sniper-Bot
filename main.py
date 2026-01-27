import os
import sys
import yfinance as yf
import pandas as pd
import requests
from dotenv import load_dotenv

# --- 1. CONFIGURATION & SETUP ---

def setup_environment():
    """
    ตั้งค่า Environment:
    - ถ้าเจอไฟล์ .env ในเครื่อง (Local) -> โหลดค่าจากไฟล์
    - ถ้าไม่เจอ (GitHub Actions) -> โหลดจาก Secrets ของระบบ
    """
    local_env_path = r"C:\Projects\EDCA-bot\Line_token.env"
    
    if os.path.exists(local_env_path):
        load_dotenv(dotenv_path=local_env_path)
        print(f"✅ Local Mode: Loaded config from {local_env_path}")
    else:
        load_dotenv()
        print("☁️ Cloud/GitHub Mode: Using Environment Variables")

# เรียกฟังก์ชันตั้งค่าทันทีที่เริ่มโปรแกรม
setup_environment()

LINE_TOKEN = os.getenv('LINE_ACCESS_TOKEN')
USER_ID = os.getenv('LINE_USER_ID')

# 🔥 เป้าหมาย: เน้นรวย (Growth Focus)
INVESTMENT_TARGETS = {
    "🇺🇸 S&P 500 (SPY)": "SPY",
    "🇺🇸 Nasdaq (QQQM)": "QQQM"
}

# 💰 งบประมาณ: 1,000 บาท ต่อกองทุน (รวม 2,000/เดือน)
BASE_BUDGET_PER_FUND = 1000 

# --- 2. CALCULATION ENGINE (BRAIN V.3 - SNIPER) ---

def calculate_indicators(df):
    """คำนวณ RSI, Bollinger Bands, MACD และ SMA200 (Pure Python)"""
    
    # 1. RSI (14)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # 2. Bollinger Bands (20, 2)
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    df['STD20'] = df['Close'].rolling(window=20).std()
    df['LowerBand'] = df['SMA20'] - (2 * df['STD20'])
    
    # 3. MACD (12, 26, 9)
    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD_Line'] = ema12 - ema26
    df['Signal_Line'] = df['MACD_Line'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD_Line'] - df['Signal_Line']
    
    # 4. SMA 200 (เส้นค่าเฉลี่ย 200 วัน - เส้นแบ่งนรกสวรรค์)
    df['SMA200'] = df['Close'].rolling(window=200).mean()
    
    return df

def get_signal(symbol):
    print(f"🔍 Analyzing {symbol} (Sniper Mode)...")
    try:
        ticker = yf.Ticker(symbol)
        # ดึงข้อมูล 1 ปี (1y) เพื่อให้คำนวณ SMA200 ได้
        df = ticker.history(period="1y")
        
        # เช็คข้อมูลว่าพอไหม (ต้องมีเกิน 200 วัน)
        if df.empty or len(df) < 200:
            print(f"⚠️ Warning: Not enough data for SMA200 on {symbol}")
            return None

        df = calculate_indicators(df)
        
        # ดึงค่าล่าสุด (Last Closed Price)
        current_price = df['Close'].iloc[-1]
        current_rsi = df['RSI'].iloc[-1]
        lower_band = df['LowerBand'].iloc[-1]
        macd_hist = df['MACD_Hist'].iloc[-1]
        sma200 = df['SMA200'].iloc[-1]
        
        multiplier = 1.0
        status = "Normal"
        note = ""

        # --- 🎯 SNIPER LOGIC ---
        
        # 1. 🔥 Super Discount (วิกฤตคือโอกาส)
        # เงื่อนไข: RSI ต่ำกว่า 30 หรือ ราคาหลุดกรอบล่าง
        if current_rsi < 30 or current_price < lower_band:
            multiplier = 1.5
            status = "🔥 Super Discount"
            note = "(Panic Buy! ราคาถูกมาก)"
            
        # 2. 🎯 Uptrend Pullback (ย่อซื้อในขาขึ้น - ท่าไม้ตาย)
        # เงื่อนไข: ราคาอยู่เหนือ SMA200 (ขาขึ้น) แต่ RSI ย่อลงมาต่ำกว่า 45
        elif current_price > sma200 and current_rsi < 45:
            multiplier = 1.2
            status = "🎯 Uptrend Pullback"
            note = "(ย่อในขาขึ้น - น่าสะสม)"
            
        # 3. ⚠️ Overbought (แพงไปแล้ว)
        # เงื่อนไข: RSI สูงกว่า 70
        elif current_rsi > 70:
            multiplier = 0.6
            status = "⚠️ Overbought"
            note = "(ระวังดอย / ลดวงเงิน)"
            
        # 4. 🐻 Downtrend Caution (ระวังขาลง)
        # เงื่อนไข: ราคาอยู่ใต้ SMA200 และ MACD ยังเป็นลบ (แรงขายยังเยอะ)
        elif current_price < sma200 and macd_hist < 0:
            multiplier = 0.8
            status = "🐻 Downtrend"
            note = "(ขาลง - ซื้อน้อยหน่อย)"
            
        # 5. ✅ Fair Price (ปกติ)
        else:
            multiplier = 1.0
            status = "✅ Fair Price"
            note = "(ราคาปกติ)"

        return {
            "price": current_price,
            "rsi": current_rsi,
            "status": status,
            "note": note,
            "amount": BASE_BUDGET_PER_FUND * multiplier
        }
    except Exception as e:
        print(f"❌ Error analyzing {symbol}: {e}")
        return None

# --- 3. LINE REPORTING ---

def send_line_api(results):
    """ส่งข้อความเข้า LINE (Messaging API)"""
    if not LINE_TOKEN or not USER_ID:
        print("❌ Error: Missing Token or User ID")
        return 400

    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LINE_TOKEN}'
    }
    
    # สร้างข้อความรายงาน
    msg = "🚀 [Jarvis Sniper Port]\n"
    msg += "Focus: Growth (SPY/QQQM)\n"
    
    total_budget = 0
    
    for name, data in results.items():
        if data:
            msg += f"\n📌 {name}\n"
            msg += f"Stat: {data['status']}\n"
            msg += f"Note: {data['note']}\n"
            msg += f"Price: ${data['price']:.2f} (RSI: {data['rsi']:.0f})\n"
            msg += f"💰 Invest: {data['amount']:,.0f} THB\n"
            total_budget += data['amount']
    
    msg += f"\n━━━━━━━━━━\n💸 Total Today: {total_budget:,.0f} THB"

    payload = {
        "to": USER_ID,
        "messages": [{"type": "text", "text": msg}]
    }
    
    response = requests.post(url, headers=headers, json=payload)
    return response.status_code

# --- 4. MAIN EXECUTION ---

if __name__ == "__main__":
    print("--- Starting Wealth Engine (Sniper Mode) ---")
    
    if not LINE_TOKEN:
        print("❌ Critical Error: LINE Token not found!")
        sys.exit(1)

    final_report = {}
    
    # วนลูปวิเคราะห์
    for name, symbol in INVESTMENT_TARGETS.items():
        result = get_signal(symbol)
        if result:
            final_report[name] = result
    
    # ส่งรายงาน
    if final_report:
        print("🚀 Sending Line Message...")
        status_code = send_line_api(final_report)
        
        if status_code == 200:
            print("✅ Mission Complete: Report Sent Successfully!")
        else:
            print(f"❌ Failed to send. Status Code: {status_code}")
            print("Check your Token and User ID again.")
    else:
        print("⚠️ No data generated. Market might be closed or API error.")
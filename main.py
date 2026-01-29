import os
import sys
import yfinance as yf
import pandas as pd
import requests
from dotenv import load_dotenv

# --- SETUP ---
def setup_environment():
    # แก้ Path ให้ตรงกับเครื่องตัวเอง
    local_env_path = r"C:\Projects\EDCA-bot\Line_token.env" 
    if os.path.exists(local_env_path):
        load_dotenv(dotenv_path=local_env_path)

setup_environment()
LINE_TOKEN = os.getenv('LINE_ACCESS_TOKEN')
USER_ID = os.getenv('LINE_USER_ID')

# 🔥 เป้าหมาย: เน้นรวย (Growth Focus)
# --- แก้ไขตรงนี้ครับ ---
INVESTMENT_TARGETS = {
    "🇹🇭 KT-US500-A": "SPY",   # แสดงชื่อไทย แต่คำนวณจากกราฟแม่ SPY
    "🇹🇭 KT-NDQ-A": "QQQ"      # แสดงชื่อไทย แต่คำนวณจากกราฟแม่ QQQ
}
# ---------------------
BASE_BUDGET_PER_FUND = 1000  # งบต่อตัว

# --- BRAIN (Calculation) ---
def calculate_indicators(df):
    # RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # Bollinger Bands
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    df['STD20'] = df['Close'].rolling(window=20).std()
    df['LowerBand'] = df['SMA20'] - (2 * df['STD20'])
    
    # MACD
    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD_Line'] = ema12 - ema26
    df['Signal_Line'] = df['MACD_Line'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD_Line'] - df['Signal_Line']
    
    # SMA 200
    df['SMA200'] = df['Close'].rolling(window=200).mean()
    return df

def get_signal(symbol):
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="1y") # ดึง 1 ปี
        if df.empty or len(df) < 200: return None
        df = calculate_indicators(df)
        
        # ข้อมูลล่าสุด
        price = df['Close'].iloc[-1]
        rsi = df['RSI'].iloc[-1]
        lower = df['LowerBand'].iloc[-1]
        macd = df['MACD_Hist'].iloc[-1]
        sma200 = df['SMA200'].iloc[-1]
        
        multiplier = 1.0
        status = "Normal"
        note = ""

        # --- SNIPER LOGIC ---
        if rsi < 30 or price < lower: # 1. Super Discount
            multiplier = 1.5
            status = "🔥 Super Discount"
            note = "(Panic Buy! ของถูกจัด)"
        elif price > sma200 and rsi < 45: # 2. Uptrend Pullback (ท่าไม้ตาย)
            multiplier = 1.2
            status = "🎯 Uptrend Pullback"
            note = "(ย่อในขาขึ้น - น่าสะสม)"
        elif rsi > 70: # 3. Overbought
            multiplier = 0.6
            status = "⚠️ Overbought"
            note = "(แพงระยับ - ลดวงเงิน)"
        elif price < sma200 and macd < 0: # 4. Downtrend
            multiplier = 0.8
            status = "🐻 Downtrend"
            note = "(ขาลง - ซื้อเลี้ยงไข้)"
        else:
            multiplier = 1.0
            status = "✅ Fair Price"
            note = "(ราคาปกติ)"

        return {
            "name": symbol, "price": price, "rsi": rsi,
            "status": status, "note": note,
            "amount": BASE_BUDGET_PER_FUND * multiplier
        }
    except: return None

# --- LINE SENDING ---
def send_line_api(results):
    if not LINE_TOKEN: return
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {LINE_TOKEN}'}
    
    # แก้ Header ข้อความนิดหน่อยให้ตรงกับบริบท
    msg = "🚀 [Jarvis Fund Sniper]\nFocus: Thai Funds (KTAM)\n"
    total = 0
    for name, data in results.items():
        if data:
            # ตรงนี้ data['name'] จะเป็นรหัสกองแม่ (SPY/QQQ)
            # แต่ name (Key) จะเป็นชื่อไทย (KT-US500-A)
            msg += f"\n📌 {name}\nStat: {data['status']}\nNote: {data['note']}\n"
            msg += f"Ref Price: ${data['price']:.2f} (RSI: {data['rsi']:.0f})\n"
            msg += f"💰 Invest: {data['amount']:,.0f} THB\n"
            total += data['amount']
    msg += f"\n━━━━━━━━━━\n💸 Total: {total:,.0f} THB"

    requests.post(url, headers=headers, json={"to": USER_ID, "messages": [{"type": "text", "text": msg}]})

if __name__ == "__main__":
    report = {}
    for name_thai, symbol_master in INVESTMENT_TARGETS.items():
        # ส่ง ticker กองแม่ไปคำนวณ
        res = get_signal(symbol_master)
        if res: 
            # ส่งผลลัพธ์กลับมา โดยใช้ชื่อไทยเป็น Key ใน report
            report[name_thai] = res
            
    if report: send_line_api(report)

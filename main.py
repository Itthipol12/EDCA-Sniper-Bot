import os
import sys
import yfinance as yf
import pandas as pd
import requests
from dotenv import load_dotenv

# ================= ⚙️ SETUP ZONE =================
def setup_environment():
    # Path ของไฟล์ .env (แก้ให้ตรงกับเครื่องคุณ)
    local_env_path = r"C:\Projects\EDCA-bot\Line_token.env" 
    if os.path.exists(local_env_path):
        load_dotenv(dotenv_path=local_env_path)

setup_environment()
LINE_TOKEN = os.getenv('LINE_ACCESS_TOKEN')
USER_ID = os.getenv('LINE_USER_ID')

# 🔥 CONFIGURATION ใหม่: ปรับกองทุนและงบตามสั่ง
INVESTMENT_PLAN = [
    {
        "name_thai": "🇺🇸 KT-US500-A",      
        "symbol_master": "SPY",         # S&P 500
        "budget": 1500                  
    },
    {
        "name_thai": "🏥 KT-HEALTHCARE-A",
        "symbol_master": "IXJ",         # Global Healthcare ETF (ตัวแทนกลุ่มการแพทย์)
        "budget": 1500
    },
    {
        "name_thai": "🇯🇵 K-JP-D",
        "symbol_master": "EWJ",         # MSCI Japan ETF
        "budget": 1000
    }
]

# ================= 🧠 CALCULATION ZONE =================

def add_smart_money_structure(df, window=5):
    # หา Swing High/Low
    df['Swing_High'] = df['High'].rolling(window=window*2+1, center=True).max()
    df['Swing_Low'] = df['Low'].rolling(window=window*2+1, center=True).min()
    df['is_Swing_High'] = df['High'] == df['Swing_High']
    df['is_Swing_Low'] = df['Low'] == df['Swing_Low']

    # หาเทรนด์ (SMC)
    last_high = df['High'].iloc[0]
    last_low = df['Low'].iloc[0]
    trend = "Sideway"
    trends = []
    
    for i in range(len(df)):
        close = df['Close'].iloc[i]
        if df['is_Swing_High'].iloc[i]: last_high = df['High'].iloc[i]
        if df['is_Swing_Low'].iloc[i]: last_low = df['Low'].iloc[i]
        
        if close > last_high: trend = "Bullish (SMC)"
        elif close < last_low: trend = "Bearish (SMC)"
        trends.append(trend)

    df['SMC_Structure'] = trends
    return df

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
    
    # SMC
    df = add_smart_money_structure(df)
    
    return df

def get_signal(fund_info):
    symbol = fund_info['symbol_master']
    base_budget = fund_info['budget']
    
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="2y")
        if df.empty or len(df) < 200: return None
        df = calculate_indicators(df)
        
        price = df['Close'].iloc[-1]
        rsi = df['RSI'].iloc[-1]
        lower = df['LowerBand'].iloc[-1]
        smc_trend = df['SMC_Structure'].iloc[-1]
        sma200 = df['SMA200'].iloc[-1]
        
        multiplier = 1.0
        status = "Normal"
        note = ""

        # --- LOGIC DCA ---
        if (price < lower) and (smc_trend == "Bullish (SMC)"): 
            multiplier = 1.5
            status = "💎 Super Discount"
            note = "ของถูกมาก (พิจารณา DCA เพิ่ม)"
        elif rsi < 30: 
            multiplier = 1.2
            status = "🔥 Oversold"
            note = "RSI ต่ำ (น่าเก็บเพิ่ม)"
        elif rsi > 70: 
            multiplier = 1.0 
            status = "⚠️ Overbought"
            note = "ราคาแพง (DCA ตามวินัยปกติ)"
        elif (smc_trend == "Bearish (SMC)") and (price < sma200):
            multiplier = 1.0
            status = "🐻 Downtrend"
            note = "ขาลง (ถัวเฉลี่ยตามวินัย)"
        else:
            multiplier = 1.0
            status = "✅ Normal"
            note = "ราคากลางๆ"

        suggested_invest = base_budget * multiplier

        return {
            "name": fund_info['name_thai'],
            "price": price,
            "rsi": rsi,
            "status": status,
            "note": note,
            "amount": suggested_invest,
            "base_budget": base_budget
        }
    except Exception as e:
        print(f"Error {symbol}: {e}")
        return None

# ================= 📲 LINE SENDING ZONE =================
def send_line_api(results):
    if not LINE_TOKEN: return
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {LINE_TOKEN}'}
    
    msg = "📅 [Jarvis Monthly DCA]\nPlan: US / Healthcare / Japan\n"
    total_suggest = 0
    
    for res in results:
        msg += f"\n📌 {res['name']}\n"
        msg += f"Stat: {res['status']} (RSI: {res['rsi']:.0f})\n"
        msg += f"Note: {res['note']}\n"
        
        if res['amount'] == res['base_budget']:
             msg += f"💰 Invest: {res['amount']:,.0f} THB\n"
        else:
             msg += f"💰 Invest: {res['amount']:,.0f} THB (จาก {res['base_budget']})\n"
             
        total_suggest += res['amount']

    msg += f"\n━━━━━━━━━━\n"
    msg += f"💵 ยอดรวมเดือนนี้: {total_suggest:,.0f} THB"

    requests.post(url, headers=headers, json={"to": USER_ID, "messages": [{"type": "text", "text": msg}]})

# ================= ▶️ MAIN EXECUTION =================
if __name__ == "__main__":
    print("🤖 Jarvis DCA กำลังเช็คพอร์ตรายตัว...")
    results = []
    
    for plan in INVESTMENT_PLAN:
        res = get_signal(plan)
        if res: results.append(res)
            
    if results: send_line_api(results)

import os
import sys
import yfinance as yf
import pandas as pd
import requests
from dotenv import load_dotenv

# ================= ⚙️ SETUP ZONE =================
def setup_environment():
    # แก้ Path ให้ตรงกับเครื่องตัวเองถ้ารันในคอม
    local_env_path = r"C:\Projects\EDCA-bot\Line_token.env" 
    if os.path.exists(local_env_path):
        load_dotenv(dotenv_path=local_env_path)
    else:
        print("⚠️ ไม่เจอไฟล์ .env (อาจจะรันบน Cloud หรือ Path ผิด)")

setup_environment()

# ดึงค่าจาก .env
LINE_TOKEN = os.getenv('LINE_ACCESS_TOKEN') # Channel Access Token
USER_ID = os.getenv('LINE_USER_ID')         # User ID

# 🔥 เป้าหมาย: กองทุนไทย (คำนวณผ่านกองแม่ US)
INVESTMENT_TARGETS = {
    "🇹🇭 KT-US500-A": "SPY",   # กองแม่ SPDR S&P 500
    "🇹🇭 KT-NDQ-A": "QQQ"      # กองแม่ Invesco QQQ
}
BASE_BUDGET_PER_FUND = 1000   # งบลงทุนต่อตัว (บาท)

# ================= 🧠 CALCULATION ZONE =================

def add_smart_money_structure(df, window=5):
    """
    ฟังก์ชันหาโครงสร้างตลาด (SMC)
    Window = 5 คือต้องเป็นยอดสูงสุดในรอบ 5 แท่งซ้ายขวา
    """
    # 1. หา Swing High/Low
    df['Swing_High'] = df['High'].rolling(window=window*2+1, center=True).max()
    df['Swing_Low'] = df['Low'].rolling(window=window*2+1, center=True).min()
    
    df['is_Swing_High'] = df['High'] == df['Swing_High']
    df['is_Swing_Low'] = df['Low'] == df['Swing_Low']

    # 2. หาเทรนด์จาก Break of Structure (BOS)
    last_high = df['High'].iloc[0]
    last_low = df['Low'].iloc[0]
    trend = "Sideway"
    trends = []
    
    for i in range(len(df)):
        close = df['Close'].iloc[i]
        
        # อัปเดต Swing ล่าสุด
        if df['is_Swing_High'].iloc[i]:
            last_high = df['High'].iloc[i]
        if df['is_Swing_Low'].iloc[i]:
            last_low = df['Low'].iloc[i]
            
        # เช็คการเบรกโครงสร้าง
        if close > last_high:
            trend = "Bullish (SMC)" # ขาขึ้น (เจ้าดันราคา)
        elif close < last_low:
            trend = "Bearish (SMC)" # ขาลง (เจ้าทิ้งของ)
            
        trends.append(trend)

    df['SMC_Structure'] = trends
    return df

def calculate_indicators(df):
    # --- 1. RSI (14) ---
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # --- 2. Bollinger Bands (20, 2) ---
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    df['STD20'] = df['Close'].rolling(window=20).std()
    df['LowerBand'] = df['SMA20'] - (2 * df['STD20'])
    
    # --- 3. MACD (12, 26, 9) ---
    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD_Line'] = ema12 - ema26
    df['Signal_Line'] = df['MACD_Line'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD_Line'] - df['Signal_Line']
    
    # --- 4. SMA 200 (Trend) ---
    df['SMA200'] = df['Close'].rolling(window=200).mean()

    # --- 5. Smart Money Structure (SMC) ---
    df = add_smart_money_structure(df)
    
    return df

def get_signal(symbol):
    try:
        # ดึงข้อมูลย้อนหลัง 2 ปี เพื่อให้ SMA200 คำนวณได้แม่นยำ
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="2y") 
        
        if df.empty or len(df) < 200: 
            return None
            
        df = calculate_indicators(df)
        
        # ดึงค่าล่าสุด (Latest Data)
        price = df['Close'].iloc[-1]
        rsi = df['RSI'].iloc[-1]
        lower = df['LowerBand'].iloc[-1]
        macd = df['MACD_Hist'].iloc[-1]
        sma200 = df['SMA200'].iloc[-1]
        smc_trend = df['SMC_Structure'].iloc[-1] # ค่า SMC ล่าสุด
        
        multiplier = 1.0
        status = "Normal"
        note = ""

        # ================= 🎯 SNIPER LOGIC (EDCA) =================
        
        # 1. Super Discount (หลุด BB + โครงสร้างยังเป็นขาขึ้น)
        if (price < lower) and (smc_trend == "Bullish (SMC)"): 
            multiplier = 2.0
            status = "💎 SMC Sniper Buy"
            note = "(ราคาหลุดกรอบ + โครงสร้างใหญ่ยังเป็นขาขึ้น)"

        # 2. Oversold (RSI ต่ำจัด)
        elif rsi < 30: 
            multiplier = 1.5
            status = "🔥 Super Oversold"
            note = "(RSI ต่ำกว่า 30 - ของถูกจัด)"

        # 3. Uptrend Pullback (ย่อในขาขึ้น - ท่าไม้ตาย)
        elif (price > sma200) and (rsi < 45) and (smc_trend == "Bullish (SMC)"):
            multiplier = 1.2
            status = "🚀 Trend Pullback"
            note = "(ย่อตัวสวยๆ ในเทรนด์ขาขึ้น)"

        # 4. Overbought (แพงไป)
        elif rsi > 70: 
            multiplier = 0.5 
            status = "⚠️ Overbought"
            note = "(RSI สูงเกินไป - ลดวงเงิน)"

        # 5. Downtrend (ขาลงชัดเจน)
        elif (smc_trend == "Bearish (SMC)") and (price < sma200):
            multiplier = 0.8
            status = "🐻 Downtrend"
            note = "(เทรนด์ขาลง - ซื้อน้อยๆ เลี้ยงวินัย)"

        else:
            multiplier = 1.0
            status = "✅ Fair Price"
            note = f"(ราคาปกติ - {smc_trend})"

        return {
            "name": symbol, 
            "price": price, 
            "rsi": rsi,
            "status": status, 
            "note": note,
            "amount": BASE_BUDGET_PER_FUND * multiplier
        }
    except Exception as e:
        print(f"Error analyzing {symbol}: {e}")
        return None

# ================= 📲 LINE SENDING ZONE =================
def send_line_api(results):
    if not LINE_TOKEN or not USER_ID:
        print("❌ ไม่พบ Token หรือ User ID ใน .env")
        return

    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json', 
        'Authorization': f'Bearer {LINE_TOKEN}'
    }
    
    msg = "🚀 [Jarvis EDCA Sniper]\nFocus: Thai Funds (KTAM)\n"
    total_invest = 0
    
    for name_thai, data in results.items():
        if data:
            msg += f"\n📌 {name_thai}\n"
            msg += f"Stat: {data['status']}\n"
            msg += f"Note: {data['note']}\n"
            msg += f"Ref Price: ${data['price']:.2f} (RSI: {data['rsi']:.0f})\n"
            msg += f"💰 Invest: {data['amount']:,.0f} THB\n"
            total_invest += data['amount']
            
    msg += f"\n━━━━━━━━━━\n💸 Total Invest: {total_invest:,.0f} THB"

    payload = {
        "to": USER_ID, 
        "messages": [{"type": "text", "text": msg}]
    }
    
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        print("✅ ส่ง Line เรียบร้อยแล้วครับ")
    else:
        print(f"❌ ส่ง Line ไม่ผ่าน: {response.text}")

# ================= ▶️ MAIN EXECUTION =================
if __name__ == "__main__":
    print("🤖 Jarvis กำลังวิเคราะห์ตลาด... โปรดรอสักครู่")
    report = {}
    
    # วนลูปเช็คทีละกองทุน
    for name_thai, symbol_master in INVESTMENT_TARGETS.items():
        print(f"กำลังเช็ค {name_thai} (อิงกราฟ {symbol_master})...")
        res = get_signal(symbol_master) # ส่ง ticker กองแม่ไปคำนวณ
        
        if res: 
            # เก็บผลลัพธ์โดยใช้ชื่อไทยเป็น Key
            report[name_thai] = res
            
    # ส่งผลลัพธ์เข้า Line
    if report: 
        send_line_api(report)
    else:
        print("❌ ไม่ได้ข้อมูล หรือ ตลาดปิด (Data Empty)")

import algotik_tse as att
import pandas as pd
import numpy as np
from datetime import datetime
import requests
import os

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
IRAN_PROXY = os.environ.get("IRAN_PROXY")

STRATEGY = "swing"
SYMBOLS = ["خودرو", "فملی", "شتران", "شپنا", "دزهراوی", "دفارا"]


def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        response = requests.post(url, data=payload, timeout=20)
        if response.status_code == 200:
            print("SUCCESS: Telegram message sent.")
            return True
        else:
            print(f"ERROR Telegram: {response.text}")
            return False
    except Exception as e:
        print(f"ERROR Telegram connection: {e}")
        return False


def get_strategy_config():
    return {
        "name": "Swing",
        "sma_short": 10,
        "sma_long": 20,
        "rsi_period": 14,
        "atr_period": 14,
        "rsi_overbought": 75,
        "rsi_oversold": 25,
        "rsi_low": 40,
        "rsi_high": 65,
        "pe_cheap": 15,
        "pe_expensive": 30,
        "history_limit": 100,
        "atr_sl_multiplier": 1.5,
        "atr_tp_multiplier": 3.0,
    }


def normalize_symbol(s):
    if not isinstance(s, str):
        return s
    return s.replace('ي', 'ی').replace('ك', 'ک').strip()


def calculate_technical_indicators(df, config):
    s = config['sma_short']
    l = config['sma_long']
    rsi_p = config['rsi_period']
    atr_p = config['atr_period']

    # SMA
    df['SMA_short'] = df['Close'].rolling(window=s).mean()
    df['SMA_long'] = df['Close'].rolling(window=l).mean()

    # RSI
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=rsi_p).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=rsi_p).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # ATR (Average True Range)
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['ATR'] = true_range.rolling(window=atr_p).mean()

    return df


def calculate_risk_levels(entry_price, atr, config):
    """محاسبه حد ضرر و حد سود بر اساس ATR"""
    if pd.isna(atr) or atr <= 0:
        return None, None, None

    sl_distance = atr * config['atr_sl_multiplier']
    tp_distance = atr * config['atr_tp_multiplier']

    stop_loss = round(entry_price - sl_distance, 0)
    take_profit = round(entry_price + tp_distance, 0)
    risk_reward = round(tp_distance / sl_distance, 2) if sl_distance > 0 else 0

    return stop_loss, take_profit, risk_reward


def get_market_snapshot_df():
    try:
        if IRAN_PROXY:
            os.environ['HTTP_PROXY'] = IRAN_PROXY
            os.environ['HTTPS_PROXY'] = IRAN_PROXY

        snapshot = att.get_market_snapshot()

        if IRAN_PROXY:
            os.environ.pop('HTTP_PROXY', None)
            os.environ.pop('HTTPS_PROXY', None)

        return snapshot['stocks']
    except Exception as e:
        print(f"ERROR Market data: {e}")
        if IRAN_PROXY:
            os.environ.pop('HTTP_PROXY', None)
            os.environ.pop('HTTPS_PROXY', None)
        return None


def get_fundamental_data(symbol, market_df):
    if market_df is None or market_df.empty:
        return None, None
    sym_norm = normalize_symbol(symbol)
    market_df['SymbolNorm'] = market_df['Symbol'].apply(normalize_symbol)
    row = market_df[market_df['SymbolNorm'] == sym_norm]
    if row.empty:
        return None, None
    r = row.iloc[0]
    last_price = r['Last']
    eps = r['EPS']
    pe = None
    if pd.notna(eps) and eps > 0:
        pe = last_price / eps
    return pe, eps


def generate_signal(row, pe, config):
    rsi = row['RSI']
    score = 0
    reasons = []

    if rsi < config['rsi_oversold']:
        score += 3
        reasons.append(f"RSI very low ({rsi:.1f})")
    elif rsi < config['rsi_low']:
        score += 2
        reasons.append(f"RSI low ({rsi:.1f})")
    elif rsi > config['rsi_overbought']:
        score -= 3
        reasons.append(f"RSI very high ({rsi:.1f})")
    elif rsi > config['rsi_high']:
        score -= 2
        reasons.append(f"RSI high ({rsi:.1f})")

    if pd.notna(row['SMA_short']) and pd.notna(row['SMA_long']):
        if row['SMA_short'] > row['SMA_long']:
            score += 2
            reasons.append("Uptrend")
        else:
            score -= 2
            reasons.append("Downtrend")

    if pd.notna(row['SMA_short']):
        if row['Close'] > row['SMA_short']:
            score += 1
        else:
            score -= 1

    if pe is not None:
        if pe < config['pe_cheap']:
            score += 2
            reasons.append(f"P/E cheap ({pe:.1f})")
        elif pe > config['pe_expensive']:
            score -= 2
            reasons.append(f"P/E expensive ({pe:.1f})")

    if rsi > config['rsi_overbought']:
        signal = "HOLD (overbought)"
    else:
        if score >= 5:
            signal = "STRONG BUY"
        elif score >= 3:
            signal = "BUY"
        elif score <= -5:
            signal = "STRONG SELL"
        elif score <= -3:
            signal = "SELL"
        else:
            signal = "HOLD"

    return signal, score, reasons


def run_bot():
    config = get_strategy_config()
    full_message = f"🤖 گزارش ربات | {config['name']}\n"
    full_message += f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    full_message += "=" * 25 + "\n"

    market_df = get_market_snapshot_df()

    if market_df is None or market_df.empty:
        print("Market data not received (probably holiday). Skipping.")
        return

    for symbol in SYMBOLS:
        try:
            df = att.get_history(symbol, limit=config['history_limit'])
            if df is None or df.empty:
                continue

            df = calculate_technical_indicators(df, config)
            last = df.iloc[-1]

            pe, eps = get_fundamental_data(symbol, market_df)
            signal, score, reasons = generate_signal(last, pe, config)

            msg = f"\n📌 {symbol}\n"
            msg += f"💰 قیمت: {last['Close']:.0f}\n"
            msg += f"📊 RSI: {last['RSI']:.1f}\n"

            if pe is not None:
                msg += f"🏦 P/E: {pe:.1f}\n"

            msg += f"🤖 سیگنال: {signal}\n"

            # اضافه کردن حد ضرر و حد سود فقط برای سیگنال‌های خرید
            if signal in ["BUY", "STRONG BUY"]:
                sl, tp, rr = calculate_risk_levels(
                    last['Close'], last['ATR'], config
                )
                if sl is not None:
                    msg += f"🛑 حد ضرر: {sl:.0f}\n"
                    msg += f"🎯 حد سود: {tp:.0f}\n"
                    msg += f"⚖️ R/R: 1:{rr}\n"

            full_message += msg

        except Exception as e:
            print(f"ERROR in {symbol}: {e}")

    print("Sending to Telegram...")
    send_telegram_message(full_message)


if __name__ == "__main__":
    run_bot()

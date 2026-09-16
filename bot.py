import algotik_tse as att
import pandas as pd
from datetime import datetime
import requests
import os

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

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
        "sma_short": 10, "sma_long": 20, "rsi_period": 14,
        "rsi_overbought": 75, "rsi_oversold": 25,
        "rsi_low": 40, "rsi_high": 65,
        "pe_cheap": 15, "pe_expensive": 30,
        "history_limit": 100,
    }


def normalize_symbol(s):
    if not isinstance(s, str):
        return s
    return s.replace('ي', 'ی').replace('ك', 'ک').strip()


def calculate_technical_indicators(df, config):
    s = config['sma_short']
    l = config['sma_long']
    rsi_p = config['rsi_period']
    df['SMA_short'] = df['Close'].rolling(window=s).mean()
    df['SMA_long'] = df['Close'].rolling(window=l).mean()
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=rsi_p).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=rsi_p).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    return df


def get_market_snapshot_df():
    try:
        snapshot = att.get_market_snapshot()
        return snapshot['stocks']
    except Exception as e:
        print(f"ERROR Market data: {e}")
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

    if rsi < config['rsi_oversold']:
        score += 3
    elif rsi < config['rsi_low']:
        score += 2
    elif rsi > config['rsi_overbought']:
        score -= 3
    elif rsi > config['rsi_high']:
        score -= 2

    if pd.notna(row['SMA_short']) and pd.notna(row['SMA_long']):
        if row['SMA_short'] > row['SMA_long']:
            score += 2
        else:
            score -= 2

    if pd.notna(row['SMA_short']):
        if row['Close'] > row['SMA_short']:
            score += 1
        else:
            score -= 1

    if pe is not None:
        if pe < config['pe_cheap']:
            score += 2
        elif pe > config['pe_expensive']:
            score -= 2

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

    return signal


def run_bot():
    config = get_strategy_config()
    full_message = f"Bot Report | {config['name']}\n"
    full_message += f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    full_message += "=" * 30 + "\n"

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
            signal = generate_signal(last, pe, config)

            msg = f"\n{symbol}\n"
            msg += f"Price: {last['Close']}\n"
            msg += f"RSI: {last['RSI']:.1f}\n"
            if pe is not None:
                msg += f"P/E: {pe:.1f}\n"
            msg += f"Signal: {signal}\n"
            full_message += msg
        except Exception as e:
            print(f"ERROR in {symbol}: {e}")

    print("Sending to Telegram...")
    send_telegram_message(full_message)


if __name__ == "__main__":
    run_bot()

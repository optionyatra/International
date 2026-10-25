from flask import Flask, jsonify, render_template_string
from flask_sock import Sock
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
import threading
import time
import json
import os
import requests
import warnings
from datetime import datetime

# =====================================================================
# 🛠️ STRATEGY CONFIGURATION (ASSET WISE PAPER TRADING & RISK)
# =====================================================================
TIMEFRAME_INTERVAL = "5m" # Chart Timeframe
HISTORY_FILE = "trades_history.json"

# Asset-specific Stop Loss & Target parameters (Gold R:R updated to 6.0)
ASSET_CONFIG = {
    "Tether Gold (XAUTUSD)": {
        "symbol": "XAUT-USD",
        "atr_multiplier": 1.5,      # Gold SL Multiplier
        "risk_reward_ratio": 6.0    # Gold Target R:R Ratio (1:6)
    },
    "Bitcoin (BTCUSD)": {
        "symbol": "BTC-USD",
        "atr_multiplier": 2.0,      # Bitcoin SL Multiplier
        "risk_reward_ratio": 3.0    # Bitcoin Target R:R Ratio (1:3)
    }
}

# Telegram Credentials
TELEGRAM_BOT_TOKEN = "8230476679:AAFcaVSR2oVzUgAtWXyJoPmCXBN38FkrYFo"
TELEGRAM_CHAT_IDS = ["7363561056"]

# Clean yfinance warnings
warnings.filterwarnings('ignore')

app = Flask(__name__)
sock = Sock(app)

live_market_data = []

if not os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, mode='w') as f:
        json.dump([], f)

locked_signals = {
    "Tether Gold (XAUTUSD)": {
        "active": False, "signal": "NEUTRAL", "sig_time": "-", 
        "sig_price": "-", "sl": 0.0, "tgt": 0.0, "last_closed_time": ""
    },
    "Bitcoin (BTCUSD)": {
        "active": False, "signal": "NEUTRAL", "sig_time": "-", 
        "sig_price": "-", "sl": 0.0, "tgt": 0.0, "last_closed_time": ""
    }
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CSB - Master Paper Trading Workstation</title>
    <style>
        body { background-color: #0f172a; color: #f8fafc; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; position: relative; }
        .live-clock { position: absolute; left: 25px; top: 20px; background: #1e293b; border: 2px solid #0284c7; padding: 12px 22px; border-radius: 10px; font-size: 17px; font-weight: bold; color: #38bdf8; box-shadow: 0 6px 20px rgba(0,0,0,0.5); letter-spacing: 0.5px; }
        h2 { color: #38bdf8; text-align: center; margin-bottom: 5px; margin-top: 15px; }
        p.subtitle { color: #94a3b8; text-align: center; margin-bottom: 20px; font-size: 14px; }
        .tabs { display: flex; justify-content: center; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }
        .tab-btn { background-color: #1e293b; color: #94a3b8; border: 1px solid #334155; padding: 10px 18px; cursor: pointer; border-radius: 6px; font-weight: 600; }
        .tab-btn.active { background-color: #0284c7; color: #fff; border-color: #0284c7; }
        .tab-content { display: none; max-width: 1400px; margin: 0 auto; background: #1e293b; padding: 25px; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }
        .tab-content.active { display: block; }
        table { width: 100%; border-collapse: collapse; text-align: center; margin-top: 10px; }
        th, td { padding: 12px 6px; border-bottom: 1px solid #334155; font-size: 13px; vertical-align: middle; }
        th { background-color: #0f172a; color: #38bdf8; }
        .bullish { color: #4ade80; font-weight: bold; }
        .bearish { color: #f87171; font-weight: bold; }
        .badge { padding: 5px 8px; border-radius: 6px; font-size: 11px; font-weight: bold; }
        .badge-buy { background: rgba(74, 222, 128, 0.15); color: #4ade80; border: 1px solid #4ade80; }
        .badge-sell { background: rgba(248, 113, 113, 0.15); color: #f87171; border: 1px solid #f87171; }
        .badge-neutral { background: rgba(148, 163, 184, 0.15); color: #94a3b8; border: 1px solid #334155; }
        .ratio-tag { display: inline-block; background: #0f172a; color: #f59e0b; border: 1px solid #f59e0b; font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-top: 4px; font-weight: 600; }
        .stats-card { display: flex; gap: 20px; justify-content: space-around; background: #0f172a; padding: 15px; border-radius: 8px; margin-bottom: 15px; border: 1px solid #334155; }
        .stat-item { text-align: center; }
        .stat-val { font-size: 18px; font-weight: bold; margin-top: 4px; }
        .refresh-status { text-align: center; margin-top: 15px; font-size: 12px; color: #4ade80; }
    </style>
</head>
<body>

    <div id="live-clock" class="live-clock">🕒 Loading IST Clock...</div>

    <h2>⚡ Chandrapur Share Bazar - Master Paper Trading</h2>
    <p class="subtitle">5-Minute Timeframe Synced with TradingView + Telegram Alerts</p>
    
    <div class="tabs">
        <button class="tab-btn active" onclick="openTab(event, 'tab1')">📊 Live Screener</button>
        <button class="tab-btn" onclick="openTab(event, 'tab2')">🧱 Prev Day Pivots (S&R)</button>
        <button class="tab-btn" onclick="openTab(event, 'tab3')">🪙 Gold Paper History</button>
        <button class="tab-btn" onclick="openTab(event, 'tab4')">₿ Bitcoin Paper History</button>
    </div>

    <div id="tab1" class="tab-content active">
        <h3>Active Master Signals & Locked Execution Levels</h3>
        <table>
            <thead>
                <tr>
                    <th>Asset & Risk Ratio</th>
                    <th>Current Price</th>
                    <th>Master Signal</th>
                    <th>Trigger Time (IST)</th>
                    <th>Exact Entry Price</th>
                    <th>Price Diff</th>
                    <th>Stop Loss</th>
                    <th>Target</th>
                </tr>
            </thead>
            <tbody id="screener-data">
                <tr><td colspan="8">Connecting real-time feed...</td></tr>
            </tbody>
        </table>
    </div>

    <div id="tab2" class="tab-content">
        <h3>Previous Day H-L-C Support & Resistance</h3>
        <table>
            <thead>
                <tr>
                    <th>Asset</th>
                    <th>Current Price</th>
                    <th>Resistance 2 (R2)</th>
                    <th>Resistance 1 (R1)</th>
                    <th>Pivot Point (P)</th>
                    <th>Support 1 (S1)</th>
                    <th>Support 2 (S2)</th>
                </tr>
            </thead>
            <tbody id="sr-data">
                <tr><td colspan="7">Calculating pivots...</td></tr>
            </tbody>
        </table>
    </div>

    <div id="tab3" class="tab-content">
        <h3>🪙 Tether Gold (XAUTUSD) - Paper Trading History</h3>
        <div class="stats-card">
            <div class="stat-item"><div>Total Trades</div><div id="gold-total-trades" class="stat-val">0</div></div>
            <div class="stat-item"><div>Total P&L ($)</div><div id="gold-total-pnl" class="stat-val">$0.00</div></div>
            <div class="stat-item"><div>Win Rate</div><div id="gold-win-rate" class="stat-val">0%</div></div>
        </div>
        <table>
            <thead>
                <tr>
                    <th>Signal</th>
                    <th>Trigger Time</th>
                    <th>Entry Price</th>
                    <th>Exit Price</th>
                    <th>Exit Time</th>
                    <th>Result</th>
                    <th>P&L ($)</th>
                </tr>
            </thead>
            <tbody id="gold-history-data">
                <tr><td colspan="7">No Gold paper trades recorded yet...</td></tr>
            </tbody>
        </table>
    </div>

    <div id="tab4" class="tab-content">
        <h3>₿ Bitcoin (BTCUSD) - Paper Trading History</h3>
        <div class="stats-card">
            <div class="stat-item"><div>Total Trades</div><div id="btc-total-trades" class="stat-val">0</div></div>
            <div class="stat-item"><div>Total P&L ($)</div><div id="btc-total-pnl" class="stat-val">$0.00</div></div>
            <div class="stat-item"><div>Win Rate</div><div id="btc-win-rate" class="stat-val">0%</div></div>
        </div>
        <table>
            <thead>
                <tr>
                    <th>Signal</th>
                    <th>Trigger Time</th>
                    <th>Entry Price</th>
                    <th>Exit Price</th>
                    <th>Exit Time</th>
                    <th>Result</th>
                    <th>P&L ($)</th>
                </tr>
            </thead>
            <tbody id="btc-history-data">
                <tr><td colspan="7">No Bitcoin paper trades recorded yet...</td></tr>
            </tbody>
        </table>
    </div>

    <div class="refresh-status">🟢 Live WebSocket Connected & Telegram Active</div>

    <script>
        function updateClock() {
            const now = new Date();
            const options = { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true };
            const timeString = new Intl.DateTimeFormat('en-US', options).format(now);
            const dateString = now.toLocaleDateString('en-GB', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric' });
            document.getElementById('live-clock').innerHTML = `🕒 ${dateString} | ${timeString}`;
        }
        setInterval(updateClock, 1000);
        updateClock();

        function openTab(evt, tabName) {
            let contents = document.getElementsByClassName("tab-content");
            for (let c of contents) c.classList.remove("active");
            let buttons = document.getElementsByClassName("tab-btn");
            for (let b of buttons) b.classList.remove("active");
            document.getElementById(tabName).classList.add("active");
            evt.currentTarget.classList.add("active");
        }

        const ws = new WebSocket('ws://' + window.location.host + '/ws');
        
        ws.onmessage = function(event) {
            let res = JSON.parse(event.data);
            let marketData = res.market;
            let historyData = res.history;

            let sHtml = '', srHtml = '';
            let goldHtml = '', btcHtml = '';

            let goldTrades = [], btcTrades = [];
            let goldPnl = 0, btcPnl = 0;
            let goldWins = 0, btcWins = 0;

            marketData.forEach(item => {
                let badge = 'badge-neutral';
                if (item.signal.includes('BUY')) badge = 'badge-buy';
                if (item.signal.includes('SELL')) badge = 'badge-sell';
                let diffColor = item.price_diff >= 0 ? 'bullish' : 'bearish';
                
                sHtml += `<tr>
                    <td>
                        <strong>${item.asset}</strong><br>
                        <span class="ratio-tag">SL: ${item.atr_mult}x ATR | R:R 1:${item.rr_ratio}</span>
                    </td>
                    <td>$${item.price.toFixed(2)}</td>
                    <td><span class="badge ${badge}">${item.signal}</span></td>
                    <td><span style="color:#38bdf8; font-weight:600;">${item.sig_time}</span></td>
                    <td><strong>${item.sig_price !== '-' ? '$' + item.sig_price : '-'}</strong></td>
                    <td class="${diffColor}">${item.price_diff !== 0 ? (item.price_diff > 0 ? '+' + item.price_diff.toFixed(2) : item.price_diff.toFixed(2)) : '0.00'}</td>
                    <td class="bearish">${item.sl !== '-' ? '$' + item.sl : '-'}</td>
                    <td class="bullish">${item.tgt !== '-' ? '$' + item.tgt : '-'}</td>
                </tr>`;

                srHtml += `<tr>
                    <td><strong>${item.asset}</strong></td>
                    <td>$${item.price.toFixed(2)}</td>
                    <td class="bearish">$${item.r2}</td>
                    <td class="bearish">$${item.r1}</td>
                    <td style="color:#38bdf8; font-weight:bold;">$${item.pivot}</td>
                    <td class="bullish">$${item.s1}</td>
                    <td class="bullish">$${item.s2}</td>
                </tr>`;
            });

            historyData.slice().reverse().forEach(h => {
                let pnlVal = parseFloat(h.pnl);
                let pnlColor = pnlVal >= 0 ? 'bullish' : 'bearish';
                let row = `<tr>
                    <td><span class="badge ${h.signal.includes('BUY') ? 'badge-buy' : 'badge-sell'}">${h.signal}</span></td>
                    <td>${h.trigger_time}</td>
                    <td>$${h.entry}</td>
                    <td>$${h.exit}</td>
                    <td><span style="color:#38bdf8; font-weight:600;">${h.exit_time || '-'}</span></td>
                    <td><strong>${h.reason}</strong></td>
                    <td class="${pnlColor}">${pnlVal > 0 ? '+' : ''}$${pnlVal.toFixed(2)}</td>
                </tr>`;

                if (h.asset.includes('Gold')) {
                    goldHtml += row;
                    goldTrades.push(h);
                    goldPnl += pnlVal;
                    if (pnlVal > 0) goldWins++;
                } else if (h.asset.includes('Bitcoin')) {
                    btcHtml += row;
                    btcTrades.push(h);
                    btcPnl += pnlVal;
                    if (pnlVal > 0) btcWins++;
                }
            });

            document.getElementById('gold-total-trades').innerText = goldTrades.length;
            document.getElementById('gold-total-pnl').innerHTML = `<span class="${goldPnl >= 0 ? 'bullish' : 'bearish'}">${goldPnl >= 0 ? '+' : ''}$${goldPnl.toFixed(2)}</span>`;
            document.getElementById('gold-win-rate').innerText = goldTrades.length > 0 ? ((goldWins / goldTrades.length) * 100).toFixed(1) + '%' : '0%';
            document.getElementById('gold-history-data').innerHTML = goldHtml || `<tr><td colspan="7">No Gold paper trades recorded yet.</td></tr>`;

            document.getElementById('btc-total-trades').innerText = btcTrades.length;
            document.getElementById('btc-total-pnl').innerHTML = `<span class="${btcPnl >= 0 ? 'bullish' : 'bearish'}">${btcPnl >= 0 ? '+' : ''}$${btcPnl.toFixed(2)}</span>`;
            document.getElementById('btc-win-rate').innerText = btcTrades.length > 0 ? ((btcWins / btcTrades.length) * 100).toFixed(1) + '%' : '0%';
            document.getElementById('btc-history-data').innerHTML = btcHtml || `<tr><td colspan="7">No Bitcoin paper trades recorded yet.</td></tr>`;

            document.getElementById('screener-data').innerHTML = sHtml;
            document.getElementById('sr-data').innerHTML = srHtml;
        };
    </script>
</body>
</html>
"""

def send_telegram_alert(message):
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            print(f"Telegram error: {e}")

def save_trade_to_json(trade):
    trades = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, mode='r') as f:
                trades = json.load(f)
        except:
            trades = []
    
    exists = any(t['asset'] == trade['asset'] and t['trigger_time'] == trade['trigger_time'] and t['reason'] == trade['reason'] for t in trades)
    if not exists:
        trades.append(trade)
        with open(HISTORY_FILE, mode='w') as f:
            json.dump(trades, f, indent=4)
        
        msg = f"📜 *CSB Paper Trade Closed*\n\n" \
              f"📌 *Asset:* {trade['asset']}\n" \
              f"📊 *Signal:* {trade['signal']}\n" \
              f"⏱️ *Trigger:* {trade['trigger_time']}\n" \
              f"💵 *Entry:* ${trade['entry']} | *Exit:* ${trade['exit']}\n" \
              f"📢 *Result:* {trade['reason']}\n" \
              f"💰 *P&L:* ${trade['pnl']}"
        send_telegram_alert(msg)

def get_history_from_json():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, mode='r') as f:
                return json.load(f)
        except:
            return []
    return []

def analyze_asset(name):
    global locked_signals
    config = ASSET_CONFIG[name]
    symbol = config["symbol"]
    atr_mult = config["atr_multiplier"]
    rr_ratio = config["risk_reward_ratio"]

    try:
        df = yf.download(symbol, period="5d", interval=TIMEFRAME_INTERVAL, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = df.index.tz_convert('Asia/Kolkata')
        
        ticker_obj = yf.Ticker(symbol)
        
        try:
            curr_price = float(ticker_obj.fast_info.last_price)
        except:
            todays_data = ticker_obj.history(period="1d", interval="1m")
            curr_price = float(todays_data['Close'].iloc[-1]) if not todays_data.empty else float(df['Close'].iloc[-1])

        daily_df = df.resample('D').agg({'High': 'max', 'Low': 'min', 'Close': 'last'}).dropna()
        prev_day = daily_df.iloc[-2] if len(daily_df) >= 2 else daily_df.iloc[-1]
        prev_h, prev_l, prev_c = float(prev_day['High']), float(prev_day['Low']), float(prev_day['Close'])

        pivot = (prev_h + prev_l + prev_c) / 3.0
        r1 = (2.0 * pivot) - prev_l
        s1 = (2.0 * pivot) - prev_h
        r2 = pivot + (prev_h - prev_l)
        s2 = pivot - (prev_h - prev_l)

        df['EMA10'] = ta.ema(df['Close'], length=10)
        df['EMA20'] = ta.ema(df['Close'], length=20)
        df['RSI'] = ta.rsi(df['Close'], length=14)
        df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
        
        bb = ta.bbands(df['Close'], length=20, std=2.0)
        df['BBM'] = bb.iloc[:, 1]

        conditions_buy = (df['EMA10'] > df['EMA20']) & (df['RSI'] > 48) & (df['Close'] > df['BBM'])
        conditions_sell = (df['EMA10'] < df['EMA20']) & (df['RSI'] < 52) & (df['Close'] < df['BBM'])

        df['Signal'] = "NEUTRAL"
        df.loc[conditions_buy, 'Signal'] = "BUY / BULLISH SETUP"
        df.loc[conditions_sell, 'Signal'] = "SELL / BEARISH SETUP"

        curr_signal = df['Signal'].iloc[-1]
        state = locked_signals[name]
        atr = float(df['ATR'].iloc[-1])

        if state["active"]:
            entry = state["sig_price"]
            sig_type = state["signal"]

            if "BUY" in sig_type:
                sl = round(entry - (atr_mult * atr), 2)
                tgt = round(entry + (atr_mult * atr * rr_ratio), 2)
            else:
                sl = round(entry + (atr_mult * atr), 2)
                tgt = round(entry - (atr_mult * atr * rr_ratio), 2)
            
            state["sl"] = sl
            state["tgt"] = tgt

            hit_exit = False
            exit_reason = ""
            pnl = 0.0

            if "BUY" in sig_type:
                if curr_price >= tgt:
                    hit_exit = True
                    exit_reason = "🎯 TARGET HIT"
                    pnl = round(tgt - entry, 2)
                elif curr_price <= sl:
                    hit_exit = True
                    exit_reason = "❌ STOP LOSS HIT"
                    pnl = round(sl - entry, 2)
            elif "SELL" in sig_type:
                if curr_price <= tgt:
                    hit_exit = True
                    exit_reason = "🎯 TARGET HIT"
                    pnl = round(entry - tgt, 2)
                elif curr_price >= sl:
                    hit_exit = True
                    exit_reason = "❌ STOP LOSS HIT"
                    pnl = round(entry - sl, 2)

            if hit_exit:
                trade_record = {
                    "asset": name,
                    "signal": sig_type,
                    "trigger_time": state["sig_time"],
                    "entry": entry,
                    "exit": round(curr_price, 2),
                    "exit_time": datetime.now().strftime("%d %b, %I:%M:%S %p"),
                    "reason": exit_reason,
                    "pnl": pnl,
                    "timestamp": datetime.now().strftime("%d %b %Y, %I:%M %p")
                }
                save_trade_to_json(trade_record)
                locked_signals[name] = {
                    "active": False, "signal": "NEUTRAL", "sig_time": "-", 
                    "sig_price": "-", "sl": 0.0, "tgt": 0.0, "last_closed_time": state["sig_time"]
                }
                state = locked_signals[name]

        if not state["active"] and curr_signal != "NEUTRAL":
            streak_mask = (df['Signal'] != curr_signal)[::-1].cumsum()[::-1]
            last_streak = df[streak_mask == streak_mask.iloc[-1]]
            trigger_candle = last_streak.iloc[0]
            trigger_time = last_streak.index[0]
            
            sig_time_str = trigger_time.strftime("%d %b, %I:%M %p")

            if sig_time_str != state["last_closed_time"]:
                sig_price = round(float(trigger_candle['Open']), 2)

                if "BUY" in curr_signal:
                    sl = round(sig_price - (atr_mult * atr), 2)
                    tgt = round(sig_price + (atr_mult * atr * rr_ratio), 2)
                else:
                    sl = round(sig_price + (atr_mult * atr), 2)
                    tgt = round(sig_price - (atr_mult * atr * rr_ratio), 2)

                locked_signals[name] = {
                    "active": True,
                    "signal": curr_signal,
                    "sig_time": sig_time_str,
                    "sig_price": sig_price,
                    "sl": sl,
                    "tgt": tgt,
                    "last_closed_time": state["last_closed_time"]
                }
                state = locked_signals[name]

                alert_msg = f"🚨 *New Paper Trade Signal Locked!*\n\n" \
                            f"📌 *Asset:* {name}\n" \
                            f"📊 *Signal:* {curr_signal}\n" \
                            f"⏰ *Time:* {sig_time_str}\n" \
                            f"💵 *Entry:* ${sig_price}\n" \
                            f"🛑 *Stop Loss:* ${sl}\n" \
                            f"🎯 *Target:* ${tgt}\n" \
                            f"⚙️ *Risk:* {atr_mult}x ATR | *R:R:* 1:{rr_ratio}"
                send_telegram_alert(alert_msg)

        sig_price_val = state["sig_price"]
        price_diff = round(curr_price - sig_price_val, 2) if sig_price_val != "-" else 0.0

        return {
            "asset": name,
            "atr_mult": atr_mult,
            "rr_ratio": rr_ratio,
            "price": curr_price,
            "signal": state["signal"],
            "sig_time": state["sig_time"],
            "sig_price": state["sig_price"],
            "price_diff": price_diff,
            "sl": state["sl"] if state["sl"] != 0.0 else "-",
            "tgt": state["tgt"] if state["tgt"] != 0.0 else "-",
            "pivot": round(pivot, 2),
            "r1": round(r1, 2),
            "r2": round(r2, 2),
            "s1": round(s1, 2),
            "s2": round(s2, 2)
        }
    except Exception as e:
        print(f"Error for {name}: {e}")
        return None

def background_calculator():
    global live_market_data
    while True:
        results = []
        for name in ASSET_CONFIG:
            res = analyze_asset(name)
            if res:
                results.append(res)

        if results:
            live_market_data = results
        time.sleep(1)

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/data')
def api_data():
    return jsonify({
        "market": live_market_data,
        "history": get_history_from_json()
    })

@sock.route('/ws')
def websocket_feed(ws):
    while True:
        payload = {
            "market": live_market_data,
            "history": get_history_from_json()
        }
        ws.send(json.dumps(payload))
        time.sleep(1)

if __name__ == '__main__':
    t = threading.Thread(target=background_calculator, daemon=True)
    t.start()
    app.run(debug=True, port=5000)
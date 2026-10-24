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
# 🛠️ STRATEGY & PAPER TRADING CONFIGURATION
# =====================================================================
ATR_MULTIPLIER = 1.5      
RISK_REWARD_RATIO = 4.5   
TIMEFRAME_INTERVAL = "5m" 
HISTORY_FILE = "trades_history.json"
ACCOUNT_FILE = "account_state.json"

# Telegram Credentials
TELEGRAM_BOT_TOKEN = "8230476679:AAFcaVSR2oVzUgAtWXyJoPmCXBN38FkrYFo"
TELEGRAM_CHAT_IDS = ["7363561056"]

warnings.filterwarnings('ignore')

app = Flask(__name__)
sock = Sock(app)

live_market_data = []

# Initialize Account State (₹1,00,000 INR Capital)
if not os.path.exists(ACCOUNT_FILE):
    initial_account = {
        "initial_capital_inr": 100000.0,
        "current_balance_inr": 100000.0,
        "usd_to_inr_rate": 83.5
    }
    with open(ACCOUNT_FILE, mode='w') as f:
        json.dump(initial_account, f)

if not os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, mode='w') as f:
        json.dump([], f)

locked_signals = {
    "Tether Gold (XAUTUSD)": {
        "active": False, "signal": "NEUTRAL", "sig_time": "-", 
        "sig_price": "-", "sl": 0.0, "tgt": 0.0, "last_closed_time": "", "qty": 0.0, "invested_inr": 0.0
    },
    "Bitcoin (BTCUSD)": {
        "active": False, "signal": "NEUTRAL", "sig_time": "-", 
        "sig_price": "-", "sl": 0.0, "tgt": 0.0, "last_closed_time": "", "qty": 0.0, "invested_inr": 0.0
    }
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CSB - Master Workstation & Paper Trading</title>
    <style>
        body { background-color: #0f172a; color: #f8fafc; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; }
        h2 { color: #38bdf8; text-align: center; margin-bottom: 5px; }
        p.subtitle { color: #94a3b8; text-align: center; margin-bottom: 20px; font-size: 14px; }
        
        /* Summary Cards */
        .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px; max-width: 1400px; margin: 0 auto 20px auto; }
        .metric-card { background: #1e293b; padding: 20px; border-radius: 10px; border: 1px solid #334155; text-align: center; }
        .metric-card h6 { margin: 0 0 8px 0; color: #94a3b8; font-size: 13px; text-transform: uppercase; }
        .metric-card h3 { margin: 0; font-size: 22px; color: #f8fafc; }

        .tabs { display: flex; justify-content: center; gap: 10px; margin-bottom: 20px; }
        .tab-btn { background-color: #1e293b; color: #94a3b8; border: 1px solid #334155; padding: 10px 20px; cursor: pointer; border-radius: 6px; font-weight: 600; }
        .tab-btn.active { background-color: #0284c7; color: #fff; border-color: #0284c7; }
        .tab-content { display: none; max-width: 1400px; margin: 0 auto; background: #1e293b; padding: 25px; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }
        .tab-content.active { display: block; }
        
        table { width: 100%; border-collapse: collapse; text-align: center; margin-top: 10px; }
        th, td { padding: 12px 6px; border-bottom: 1px solid #334155; font-size: 13px; }
        th { background-color: #0f172a; color: #38bdf8; }
        .bullish { color: #4ade80; font-weight: bold; }
        .bearish { color: #f87171; font-weight: bold; }
        .badge { padding: 5px 8px; border-radius: 6px; font-size: 11px; font-weight: bold; }
        .badge-buy { background: rgba(74, 222, 128, 0.15); color: #4ade80; border: 1px solid #4ade80; }
        .badge-sell { background: rgba(248, 113, 113, 0.15); color: #f87171; border: 1px solid #f87171; }
        .badge-neutral { background: rgba(148, 163, 184, 0.15); color: #94a3b8; border: 1px solid #334155; }
        .refresh-status { text-align: center; margin-top: 15px; font-size: 12px; color: #4ade80; }
    </style>
</head>
<body>

    <h2>⚡ Chandrapur Share Bazar - Automated Paper Trading Workstation</h2>
    <p class="subtitle">Live Signal Execution + ₹1,00,000 INR Virtual Capital Portfolio Manager</p>
    
    <!-- Account Summary Metrics -->
    <div class="metrics-grid">
        <div class="metric-card">
            <h6>Initial Capital</h6>
            <h3>₹1,00,000.00</h3>
        </div>
        <div class="metric-card">
            <h6>Current Balance</h6>
            <h3 id="curr-balance">₹1,00,000.00</h3>
        </div>
        <div class="metric-card">
            <h6>Total Net P&L</h6>
            <h3 id="net-pnl">₹0.00</h3>
        </div>
        <div class="metric-card">
            <h6>Win Rate</h6>
            <h3 id="win-rate">0.00%</h3>
        </div>
    </div>

    <div class="tabs">
        <button class="tab-btn active" onclick="openTab(event, 'tab1')">📊 Master Screener & Orders</button>
        <button class="tab-btn" onclick="openTab(event, 'tab2')">📈 Live TradingView Charts</button>
        <button class="tab-btn" onclick="openTab(event, 'tab3')">📜 Account Statement & Ledger</button>
    </div>

    <!-- TAB 1: Screener -->
    <div id="tab1" class="tab-content active">
        <h3>Active Signals & Executed Positions</h3>
        <table>
            <thead>
                <tr>
                    <th>Asset</th>
                    <th>Current Price</th>
                    <th>Master Signal</th>
                    <th>Entry Price</th>
                    <th>Allocated (INR)</th>
                    <th>Stop Loss</th>
                    <th>Target</th>
                </tr>
            </thead>
            <tbody id="screener-data">
                <tr><td colspan="7">Connecting feed...</td></tr>
            </tbody>
        </table>
    </div>

    <!-- TAB 2: Interactive Charts -->
    <div id="tab2" class="tab-content">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
            <h3 style="margin:0;">Live Technical Chart</h3>
            <select id="asset-chart-select" class="form-select" style="background:#0f172a; color:#fff; padding:8px 12px; border-radius:6px; border:1px solid #334155;" onchange="updateChartSymbol(this.value)">
                <option value="BINANCE:BTCUSDT">Bitcoin (BTCUSD)</option>
                <option value="PAXOS:XAUTUSD">Tether Gold (XAUTUSD)</option>
            </select>
        </div>
        <div id="tradingview_chart" style="height: 500px;"></div>
    </div>

    <!-- TAB 3: Statement History -->
    <div id="tab3" class="tab-content">
        <h3>Detailed Account Statement & Trade Log</h3>
        <table>
            <thead>
                <tr>
                    <th>Asset</th>
                    <th>Signal</th>
                    <th>Trigger Time</th>
                    <th>Entry</th>
                    <th>Exit</th>
                    <th>Reason</th>
                    <th>P&L (INR)</th>
                    <th>Balance After</th>
                </tr>
            </thead>
            <tbody id="history-data">
                <tr><td colspan="8">No closed trades recorded yet...</td></tr>
            </tbody>
        </table>
    </div>

    <div class="refresh-status">🟢 Live WebSocket Connected & Paper Execution Active</div>

    <!-- TradingView Embed Library -->
    <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
    <script type="text/javascript">
        let tvWidget;
        function updateChartSymbol(symbol) {
            tvWidget = new TradingView.widget({
                "autosize": true,
                "symbol": symbol,
                "interval": "5",
                "timezone": "Asia/Kolkata",
                "theme": "dark",
                "style": "1",
                "locale": "en",
                "toolbar_bg": "#f1f3f6",
                "enable_publishing": false,
                "container_id": "tradingview_chart"
            });
        }
        updateChartSymbol("BINANCE:BTCUSDT");

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
            let acc = res.account;

            // Update Metrics
            document.getElementById('curr-balance').innerText = '₹' + acc.current_balance_inr.toLocaleString('en-IN', {minimumFractionDigits: 2});
            let pnlColorClass = acc.total_pnl_inr >= 0 ? 'bullish' : 'bearish';
            document.getElementById('net-pnl').innerHTML = `<span class="${pnlColorClass}">₹${acc.total_pnl_inr >= 0 ? '+' : ''}${acc.total_pnl_inr.toLocaleString('en-IN', {minimumFractionDigits: 2})}</span>`;
            document.getElementById('win-rate').innerText = acc.win_rate + '%';

            let sHtml = '', hHtml = '';

            marketData.forEach(item => {
                let badge = 'badge-neutral';
                if (item.signal.includes('BUY')) badge = 'badge-buy';
                if (item.signal.includes('SELL')) badge = 'badge-sell';
                
                sHtml += `<tr>
                    <td><strong>${item.asset}</strong></td>
                    <td>$${item.price.toFixed(2)}</td>
                    <td><span class="badge ${badge}">${item.signal}</span></td>
                    <td><strong>${item.sig_price !== '-' ? '$' + item.sig_price : '-'}</strong></td>
                    <td>${item.invested_inr > 0 ? '₹' + item.invested_inr.toLocaleString('en-IN') : '-'}</td>
                    <td class="bearish">${item.sl !== '-' ? '$' + item.sl : '-'}</td>
                    <td class="bullish">${item.tgt !== '-' ? '$' + item.tgt : '-'}</td>
                </tr>`;
            });

            historyData.reverse().forEach(h => {
                let pnlColor = parseFloat(h.pnl_inr) >= 0 ? 'bullish' : 'bearish';
                hHtml += `<tr>
                    <td><strong>${h.asset}</strong></td>
                    <td><span class="badge ${h.signal.includes('BUY') ? 'badge-buy' : 'badge-sell'}">${h.signal}</span></td>
                    <td>${h.trigger_time}</td>
                    <td>$${h.entry}</td>
                    <td>$${h.exit}</td>
                    <td><strong>${h.reason}</strong></td>
                    <td class="${pnlColor}">₹${parseFloat(h.pnl_inr) > 0 ? '+' : ''}${h.pnl_inr.toLocaleString('en-IN')}</td>
                    <td>₹${h.balance_after.toLocaleString('en-IN')}</td>
                </tr>`;
            });

            if(historyData.length === 0) {
                hHtml = `<tr><td colspan="8">No closed trades recorded yet.</td></tr>`;
            }

            document.getElementById('screener-data').innerHTML = sHtml;
            document.getElementById('history-data').innerHTML = hHtml;
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

def get_account_state():
    if os.path.exists(ACCOUNT_FILE):
        try:
            with open(ACCOUNT_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {"initial_capital_inr": 100000.0, "current_balance_inr": 100000.0, "usd_to_inr_rate": 83.5}

def update_account_balance(pnl_inr):
    acc = get_account_state()
    acc["current_balance_inr"] = round(acc["current_balance_inr"] + pnl_inr, 2)
    with open(ACCOUNT_FILE, 'w') as f:
        json.dump(acc, f, indent=4)

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
        update_account_balance(trade['pnl_inr'])
        acc = get_account_state()
        trade['balance_after'] = acc['current_balance_inr']
        
        trades.append(trade)
        with open(HISTORY_FILE, mode='w') as f:
            json.dump(trades, f, indent=4)
        
        # Telegram Trade Closed Notification
        msg = f"📜 *CSB Paper Trade Closed*\n\n" \
              f"📌 *Asset:* {trade['asset']}\n" \
              f"📊 *Signal:* {trade['signal']}\n" \
              f"💵 *Entry:* ${trade['entry']} | *Exit:* ${trade['exit']}\n" \
              f"📢 *Result:* {trade['reason']}\n" \
              f"💰 *P&L:* ₹{trade['pnl_inr']:+,.2f}\n" \
              f"🏦 *New Balance:* ₹{trade['balance_after']:,.2f}"
        send_telegram_alert(msg)

def get_history_from_json():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, mode='r') as f:
                return json.load(f)
        except:
            return []
    return []

def get_account_metrics():
    acc = get_account_state()
    history = get_history_from_json()
    total_trades = len(history)
    winning_trades = sum(1 for t in history if t["pnl_inr"] > 0)
    win_rate = round((winning_trades / total_trades * 100), 2) if total_trades > 0 else 0.0
    total_pnl = round(acc["current_balance_inr"] - acc["initial_capital_inr"], 2)
    
    return {
        "initial_capital_inr": acc["initial_capital_inr"],
        "current_balance_inr": acc["current_balance_inr"],
        "total_pnl_inr": total_pnl,
        "win_rate": win_rate,
        "total_trades": total_trades
    }

def analyze_asset(name, symbol):
    global locked_signals
    try:
        df = yf.download(symbol, period="5d", interval=TIMEFRAME_INTERVAL, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = df.index.tz_convert('Asia/Kolkata')
        
        ticker_obj = yf.Ticker(symbol)
        todays_data = ticker_obj.history(period="1d", interval="1m")
        curr_price = float(todays_data['Close'].iloc[-1]) if not todays_data.empty else float(df['Close'].iloc[-1])

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

        if state["active"]:
            entry = state["sig_price"]
            sl = state["sl"]
            tgt = state["tgt"]
            sig_type = state["signal"]
            qty = state["qty"]

            hit_exit = False
            exit_reason = ""
            pnl_usd = 0.0

            if "BUY" in sig_type:
                if curr_price >= tgt:
                    hit_exit = True
                    exit_reason = "🎯 TARGET HIT"
                    pnl_usd = (tgt - entry) * qty
                elif curr_price <= sl:
                    hit_exit = True
                    exit_reason = "❌ STOP LOSS HIT"
                    pnl_usd = (sl - entry) * qty
            elif "SELL" in sig_type:
                if curr_price <= tgt:
                    hit_exit = True
                    exit_reason = "🎯 TARGET HIT"
                    pnl_usd = (entry - tgt) * qty
                elif curr_price >= sl:
                    hit_exit = True
                    exit_reason = "❌ STOP LOSS HIT"
                    pnl_usd = (entry - sl) * qty

            if hit_exit:
                acc = get_account_state()
                pnl_inr = round(pnl_usd * acc["usd_to_inr_rate"], 2)
                trade_record = {
                    "asset": name,
                    "signal": sig_type,
                    "trigger_time": state["sig_time"],
                    "entry": entry,
                    "exit": round(curr_price, 2),
                    "exit_time": datetime.now().strftime("%d %b, %I:%M:%S %p"),
                    "reason": exit_reason,
                    "pnl_inr": pnl_inr,
                    "timestamp": datetime.now().strftime("%d %b %Y, %I:%M %p")
                }
                save_trade_to_json(trade_record)
                locked_signals[name] = {
                    "active": False, "signal": "NEUTRAL", "sig_time": "-", 
                    "sig_price": "-", "sl": 0.0, "tgt": 0.0, "last_closed_time": state["sig_time"], "qty": 0.0, "invested_inr": 0.0
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
                atr = float(df['ATR'].iloc[-1])

                if "BUY" in curr_signal:
                    sl = round(sig_price - (ATR_MULTIPLIER * atr), 2)
                    tgt = round(sig_price + (ATR_MULTIPLIER * atr * RISK_REWARD_RATIO), 2)
                else:
                    sl = round(sig_price + (ATR_MULTIPLIER * atr), 2)
                    tgt = round(sig_price - (ATR_MULTIPLIER * atr * RISK_REWARD_RATIO), 2)

                # Calculate position sizing (Allocate 20% of current balance per trade)
                acc = get_account_state()
                allocated_inr = acc["current_balance_inr"] * 0.20
                allocated_usd = allocated_inr / acc["usd_to_inr_rate"]
                qty = round(allocated_usd / sig_price, 4)

                locked_signals[name] = {
                    "active": True,
                    "signal": curr_signal,
                    "sig_time": sig_time_str,
                    "sig_price": sig_price,
                    "sl": sl,
                    "tgt": tgt,
                    "last_closed_time": state["last_closed_time"],
                    "qty": qty,
                    "invested_inr": round(allocated_inr, 2)
                }
                state = locked_signals[name]

                # Telegram Trade Execution Notification
                alert_msg = f"🚨 *CSB Paper Trade Executed!*\n\n" \
                            f"📌 *Asset:* {name}\n" \
                            f"📊 *Signal:* {curr_signal}\n" \
                            f"⏰ *Time:* {sig_time_str}\n" \
                            f"💵 *Entry:* ${sig_price}\n" \
                            f"📦 *Qty:* {qty} | *Invested:* ₹{allocated_inr:,.2f}\n" \
                            f"🛑 *SL:* ${sl} | 🎯 *Target:* ${tgt}"
                send_telegram_alert(alert_msg)

        return {
            "asset": name,
            "price": curr_price,
            "signal": state["signal"],
            "sig_time": state["sig_time"],
            "sig_price": state["sig_price"],
            "sl": state["sl"] if state["sl"] != 0.0 else "-",
            "tgt": state["tgt"] if state["tgt"] != 0.0 else "-",
            "invested_inr": state["invested_inr"]
        }
    except Exception as e:
        print(f"Error for {name}: {e}")
        return None

def background_calculator():
    global live_market_data
    while True:
        results = []
        gold_res = analyze_asset("Tether Gold (XAUTUSD)", "XAUT-USD")
        if gold_res: results.append(gold_res)

        btc_res = analyze_asset("Bitcoin (BTCUSD)", "BTC-USD")
        if btc_res: results.append(btc_res)

        if results:
            live_market_data = results
        time.sleep(3)

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/data')
def api_data():
    return jsonify({
        "market": live_market_data,
        "history": get_history_from_json(),
        "account": get_account_metrics()
    })

@sock.route('/ws')
def websocket_feed(ws):
    while True:
        payload = {
            "market": live_market_data,
            "history": get_history_from_json(),
            "account": get_account_metrics()
        }
        ws.send(json.dumps(payload))
        time.sleep(1)

if __name__ == '__main__':
    t = threading.Thread(target=background_calculator, daemon=True)
    t.start()
    app.run(debug=True, port=5000)

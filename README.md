# Swing Trading Scanner — Chartink + WhatsApp

End-to-end tool that:

1. Scans **Chartink** every market day with 5 swing-trade screeners.
2. Independently re-validates each candidate using **yfinance** (RSI, MACD, EMA stack, ATR, volume, liquidity).
3. Scores each setup 0–100 and computes **entry / stop-loss / 5–15% target / R:R**.
4. Sends the top picks to your phone via **WhatsApp** (CallMeBot — free, or Twilio).

> ⚠️ **Disclaimer.** This is a research / educational tool. Past patterns ≠ future returns. Always size positions, use the stop-loss, and don't trade money you can't afford to lose.

---

## Project layout

```
TestingStock/
├── chartink_scanner.py   # POSTs scan_clauses to chartink.com/screener/process
├── analyzer.py           # OHLC pull + indicator math + scoring
├── notifier.py           # CallMeBot / Twilio / console providers
├── config.py             # .env loader
├── main.py               # CLI: run once, --schedule, --dry
├── requirements.txt
├── .env.example
├── cache/                # JSON snapshots of every run
└── logs/                 # Daily log files
```

---

## Setup (Windows)

```bash
cd c:\Users\E11420.EXTRAMARKS\Desktop\TestingStock
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Then edit `.env` with your CallMeBot details (see below).

---

## Get your free WhatsApp API key (CallMeBot)

1. Save **+34 644 51 95 23** in your phone contacts as `CallMeBot`.
2. Open WhatsApp → message that contact: `I allow callmebot to send me messages`
3. You'll get back a 7-digit API key — paste it in `.env` as `CALLMEBOT_APIKEY`.
4. Set `CALLMEBOT_PHONE` to your number with country code, no `+` (e.g. `919876543210`).

That's it — free, no Twilio account needed for personal use.

---

## Run

```bash
# one-shot, no message (development)
python main.py --dry

# one-shot, send WhatsApp
python main.py

# stay running, fire daily at 15:35 IST (Mon-Fri)
python main.py --schedule
```

Or schedule via Windows Task Scheduler — point an action at `python main.py` daily at 3:35 PM.

---

## Built-in screeners

| key | logic | typical setup |
|---|---|---|
| `momentum_breakout` | close > 20 EMA > 50 EMA, breakout above prior-day high, vol > 1.5× avg, RSI 55-75 | classic swing entry |
| `macd_bullish_cross` | MACD line crosses above signal today, price > 50 SMA | fresh momentum |
| `ema20_pullback` | uptrend (50 > 200 EMA), price tags 20 EMA and bounces | buy-the-dip |
| `near_52w_high_breakout` | within 2% of 52-week high, breakout candle, vol > 1.5× | strongest stocks |
| `volume_spike_bull` | vol > 2× avg, green candle, above 20 EMA | accumulation |

A stock appearing in **multiple** scans gets a confirmation bonus on the score.

---

## Scoring (out of 100)

| component | max |
|---|---|
| Trend alignment (above 20/50/200 EMA) | 30 |
| Momentum (RSI band + MACD posture) | 25 |
| Volume (multiple of 20-day avg) | 15 |
| Multi-scan confirmation | 15 |
| Liquidity (rupee turnover) | 15 |

Hard filters (auto-skip): below 50 EMA, RSI > 80 or < 40, stop > 8% wide, price/volume outside band.

Stop = `max(swing_low_10d × 0.995, entry − 1.5×ATR)`. Targets are 5% (low) and 15% (high) of entry, capped to a 2R+ structure where possible.

---

## Sample WhatsApp output

```
📈 *SWING PICKS — NSE*
Top 3 setups for 3-10 day hold (target 5-15%).
_Educational only. Not financial advice._

*1. TATAPOWER*  (score 82/100)
   Entry ≈ ₹412.30
   Stop  : ₹398.50  (3.3% risk)
   Target: ₹432.92 – ₹474.15  (5.0–15.0%)
   R:R ≈ 1.49   RSI 63.2
   Setup: momentum_breakout+volume_spike_bull
   • Above 200 EMA (long-term uptrend)
   • RSI 63 in healthy momentum zone
   • Volume 2.4x avg — strong accumulation
```

---

## Tuning

All thresholds live in `.env`:

```
MIN_PRICE=50          # ignore penny stocks
MAX_PRICE=5000
MIN_VOLUME=100000
TARGET_PCT_MIN=5
TARGET_PCT_MAX=15
TOP_N=10              # how many to send
```

To add or change a Chartink screener, edit `SCANS` in `chartink_scanner.py`. Chartink's [scan-clause docs](https://chartink.com/screener) describe the syntax; the same string you'd paste into the website's "Scan Conditions" box works here.

---

## Troubleshooting

- **CSRF error from Chartink** — they updated their token meta tag; re-check `_get_csrf` selector.
- **Empty results** — most often the market was closed (holiday) or your scan is too strict.
- **CallMeBot not delivering** — your free quota resets daily, ~50 messages/day. Re-confirm the activation message.
- **yfinance throttled** — increase delay in `analyzer.analyze_many` or downgrade to `period="6mo"`.

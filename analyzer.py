"""
Technical confirmation + scoring on top of Chartink hits.

For each candidate we pull ~6 months of daily OHLC from Yahoo Finance,
recompute indicators independently of Chartink (defence in depth), and produce:

  - score (0..100) — higher = more aligned setup
  - entry, stop_loss, target_low, target_high
  - reward_to_risk
  - notes (human readable)

Stocks that fail basic sanity (downtrend, RSI extreme, no liquidity) get
filtered out so the WhatsApp message is signal-rich.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

import config
from chartink_scanner import ChartinkRow

log = logging.getLogger(__name__)


# ---------- Indicator math (no TA-Lib dependency) ----------

def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(close: pd.Series, fast=12, slow=26, signal=9):
    macd_line = ema(close, fast) - ema(close, slow)
    sig = ema(macd_line, signal)
    return macd_line, sig, macd_line - sig


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["High"], df["Low"], df["Close"]
    tr = pd.concat([
        (h - l).abs(),
        (h - c.shift()).abs(),
        (l - c.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def bb_width(close: pd.Series, n: int = 20) -> pd.Series:
    sma_val = close.rolling(n).mean()
    std = close.rolling(n).std()
    upper = sma_val + (std * 2)
    lower = sma_val - (std * 2)
    return (upper - lower) / sma_val


# ---------- Pick model ----------

@dataclass
class Pick:
    symbol: str
    name: str
    scan: str
    price: float
    entry: float
    stop_loss: float
    target_low: float
    target_high: float
    rr: float
    score: int
    rsi: float
    notes: List[str] = field(default_factory=list)

    @property
    def upside_low_pct(self) -> float:
        return (self.target_low / self.entry - 1) * 100

    @property
    def upside_high_pct(self) -> float:
        return (self.target_high / self.entry - 1) * 100

    @property
    def risk_pct(self) -> float:
        return (1 - self.stop_loss / self.entry) * 100


def _ohlc(symbol: str, period: str = "9mo") -> Optional[pd.DataFrame]:
    """Fetch daily OHLC. Chartink uses NSE codes; Yahoo wants the .NS suffix."""
    yf_sym = f"{symbol}.NS"
    if symbol == "^NSEI":
        yf_sym = symbol
    try:
        df = yf.download(yf_sym, period=period, progress=False, auto_adjust=False)
    except Exception as e:  # noqa: BLE001
        log.warning("yfinance failed for %s: %s", yf_sym, e)
        return None
    if df is None or df.empty or len(df) < 60:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


_NIFTY_CACHE = {}

def _nifty_trend() -> bool:
    if not config.CHECK_NIFTY_TREND:
        return True
    if "trend" in _NIFTY_CACHE:
        return _NIFTY_CACHE["trend"]
    
    df = _ohlc("^NSEI", period="6mo")
    if df is None:
        _NIFTY_CACHE["trend"] = True # default to true if fails
        return True
    
    close = df["Close"]
    e50 = ema(close, 50).iloc[-1]
    is_uptrend = float(close.iloc[-1]) > e50
    _NIFTY_CACHE["trend"] = is_uptrend
    if not is_uptrend:
        log.warning("Nifty 50 is below 50 EMA. Market regime is weak.")
    return is_uptrend


def analyze(row: ChartinkRow, nifty_uptrend: bool = True) -> Optional[Pick]:
    df = _ohlc(row.nse_code)
    if df is None:
        log.info("No OHLC for %s, skipping", row.nse_code)
        return None

    close = df["Close"]
    last = float(close.iloc[-1])

    e20 = ema(close, 20).iloc[-1]
    e50 = ema(close, 50).iloc[-1]
    e200 = ema(close, 200).iloc[-1] if len(close) >= 200 else e50
    s_rsi = float(rsi(close).iloc[-1])
    macd_line, macd_sig, _ = macd(close)
    macd_now = float(macd_line.iloc[-1])
    macd_prev = float(macd_line.iloc[-2])
    sig_now = float(macd_sig.iloc[-1])
    a = float(atr(df).iloc[-1])

    # Recent swing low (last 10 sessions) for stop-loss
    swing_low = float(df["Low"].tail(10).min())

    # Avg volume filter
    avg_vol_20 = float(df["Volume"].tail(20).mean())
    last_vol = float(df["Volume"].iloc[-1])

    score = 0
    notes: List[str] = []

    if not nifty_uptrend:
        notes.append("Market Regime: Nifty below 50 EMA (Caution)")
        score -= 20

    # --- Trend alignment (max 30) ---
    if last > e20 and e20 > e50 and e50 > e200:
        score += 30
        notes.append("Perfect Trend: Price > 20 > 50 > 200 EMA")
    else:
        if last > e20: score += 8
        if last > e50: score += 10
        if last > e200: 
            score += 12
            notes.append("Above 200 EMA (long-term uptrend)")
        else:
            notes.append("Below 200 EMA — weaker trend backdrop")

    # --- BB Squeeze (max 10) ---
    bbw = float(bb_width(close).iloc[-1])
    if bbw < 0.15: # 15% width
        score += 10
        notes.append("Bollinger Band Squeeze (VCP)")

    # --- Momentum (max 25) ---
    if 50 <= s_rsi <= 70:
        score += 15
        notes.append(f"RSI {s_rsi:.0f} in healthy momentum zone")
    elif 70 < s_rsi <= 78:
        score += 8
        notes.append(f"RSI {s_rsi:.0f} hot — small position")
    elif 45 <= s_rsi < 50:
        score += 6
    else:
        notes.append(f"RSI {s_rsi:.0f} — outside ideal 50-70 band")

    if macd_now > sig_now:
        score += 6
        if macd_prev <= sig_now:
            score += 4
            notes.append("Fresh MACD bullish cross")

    # --- Volume (max 15) ---
    vol_mult = last_vol / avg_vol_20 if avg_vol_20 else 0
    if vol_mult >= 2:
        score += 15
        notes.append(f"Volume {vol_mult:.1f}x avg — strong accumulation")
    elif vol_mult >= 1.5:
        score += 10
        notes.append(f"Volume {vol_mult:.1f}x avg")
    elif vol_mult >= 1:
        score += 4

    # --- Multi-scan confirmation (max 15) ---
    n_scans = len(row.scan_name.split("+"))
    score += min(n_scans * 5, 15)
    if n_scans > 1:
        notes.append(f"Confirmed across {n_scans} scans")

    # --- Liquidity (max 15) ---
    rupee_vol = last * last_vol  # approx daily turnover
    if rupee_vol >= 50_000_000:  # 5 cr
        score += 15
    elif rupee_vol >= 10_000_000:
        score += 8
    else:
        score += 2
        notes.append("Low turnover — keep size small")

    # --- Build levels ---
    entry = last
    # Stop = max(swing_low, entry - 1.5*ATR) — whichever is tighter and structural
    atr_stop = entry - 1.5 * a
    stop = max(swing_low * 0.995, atr_stop)
    if stop >= entry:
        stop = entry * 0.96
    risk_pct = (1 - stop / entry) * 100

    # Target band 5-15%, but anchor on R-multiple too (>= 2R when possible)
    tgt_low = entry * (1 + config.TARGET_PCT_MIN / 100)
    tgt_high = entry * (1 + config.TARGET_PCT_MAX / 100)
    rr = (tgt_low - entry) / (entry - stop) if entry > stop else 0

    # --- Hard filters ---
    if last < config.MIN_PRICE or last > config.MAX_PRICE:
        return None
    if last_vol < config.MIN_VOLUME:
        return None
    if rupee_vol < getattr(config, "MIN_TURNOVER_CR", 10.0) * 10_000_000:
        notes.append(f"Turnover < {getattr(config, 'MIN_TURNOVER_CR', 10.0)} Cr — skipped")
        return None
    if risk_pct > 8:  # don't take trades risking more than 8%
        notes.append("Stop too wide — skipped")
        return None
    if last < e50 * 0.98:
        notes.append("Below 50 EMA — skipped")
        return None
    if s_rsi > 80 or s_rsi < 40:
        return None
    if rr < getattr(config, "MIN_RR_RATIO", 2.0):
        notes.append(f"R:R ({rr:.2f}) < {getattr(config, 'MIN_RR_RATIO', 2.0)} — skipped")
        return None

    return Pick(
        symbol=row.nse_code,
        name=row.name,
        scan=row.scan_name,
        price=last,
        entry=round(entry, 2),
        stop_loss=round(stop, 2),
        target_low=round(tgt_low, 2),
        target_high=round(tgt_high, 2),
        rr=round(rr, 2),
        score=int(score),
        rsi=round(s_rsi, 1),
        notes=notes,
    )


def analyze_many(rows: List[ChartinkRow], top_n: int) -> List[Pick]:
    picks: List[Pick] = []
    nifty_uptrend = _nifty_trend()
    for r in rows:
        try:
            p = analyze(r, nifty_uptrend)
        except Exception as e:  # noqa: BLE001
            log.warning("Analyze failed for %s: %s", r.nse_code, e)
            continue
        if p:
            picks.append(p)
    picks.sort(key=lambda p: (p.score, p.rr), reverse=True)
    return picks[:top_n]

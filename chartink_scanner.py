"""
Chartink screener client.

Chartink uses an internal POST endpoint (`/screener/process`) with a CSRF token
fetched from the screener page. We replicate that handshake.

We ship multiple scan presets tuned for swing trading (3-10 day hold, 5-15%
target). Each preset is a Chartink scan_clause string.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, List

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

CHARTINK_BASE = "https://chartink.com"
SCREEN_URL = f"{CHARTINK_BASE}/screener/"
PROCESS_URL = f"{CHARTINK_BASE}/screener/process"

# ---------- Scan presets ----------
# Each clause is what you would paste into Chartink's "Scan Conditions" box.
# Cheat-sheet:
#   latest close          = today's close
#   1 day ago close       = previous close
#   latest sma(close,50)  = 50-day SMA of close
#   latest ema(close,20)  = 20-day EMA of close
#   latest volume         = today's volume
#   latest rsi(14)        = 14-period RSI
#   latest macd line(26,12,9), latest macd signal(26,12,9)

SCANS: Dict[str, str] = {
    # 1. Bullish momentum breakout — close above 20 EMA, 50 EMA, and rising,
    #    with volume surge. Classic swing entry.
    "momentum_breakout": (
        "( {cash} ( "
        "latest close > latest ema( close,20 ) and "
        "latest ema( close,20 ) > latest ema( close,50 ) and "
        "latest close > 1 day ago high and "
        "latest volume > latest sma( volume,20 ) * 1.5 and "
        "latest rsi( 14 ) >= 55 and latest rsi( 14 ) <= 75 and "
        "latest close >= 50 and latest close <= 5000 "
        ") )"
    ),

    # 2. MACD bullish crossover with strong trend — fresh momentum entry.
    "macd_bullish_cross": (
        "( {cash} ( "
        "latest macd line( 26,12,9 ) > latest macd signal( 26,12,9 ) and "
        "1 day ago macd line( 26,12,9 ) <= 1 day ago macd signal( 26,12,9 ) and "
        "latest close > latest sma( close,50 ) and "
        "latest volume > latest sma( volume,20 ) * 1.2 and "
        "latest close >= 50 "
        ") )"
    ),

    # 3. Pullback to 20 EMA in an uptrend — buy the dip setup, low risk entry.
    "ema20_pullback": (
        "( {cash} ( "
        "latest close > latest ema( close,50 ) and "
        "latest ema( close,50 ) > latest ema( close,200 ) and "
        "latest low <= latest ema( close,20 ) * 1.02 and "
        "latest close > latest ema( close,20 ) and "
        "latest rsi( 14 ) >= 45 and latest rsi( 14 ) <= 65 and "
        "latest close >= 50 "
        ") )"
    ),

    # 4. 52-week-high breakout with volume — strongest stocks, momentum continuation.
    "near_52w_high_breakout": (
        "( {cash} ( "
        "latest close >= latest max( 250 , close ) * 0.98 and "
        "latest close > 1 day ago high and "
        "latest volume > latest sma( volume,50 ) * 1.5 and "
        "latest rsi( 14 ) >= 60 and "
        "latest close >= 50 "
        ") )"
    ),

    # 5. Volume Spike with green candle — institutional accumulation footprint.
    "volume_spike_bull": (
        "( {cash} ( "
        "latest volume > latest sma( volume,20 ) * 2.5 and "
        "latest close > latest open and "
        "latest close > latest ema( close,20 ) and "
        "latest rsi( 14 ) >= 50 and latest rsi( 14 ) <= 75 and "
        "latest close >= 50 "
        ") )"
    ),
    
    # 6. Volatility Contraction Pattern (VCP) - Squeeze with volume dry-up
    "vcp_squeeze": (
        "( {cash} ( "
        "latest close >= 50 and "
        "latest close > latest sma( close, 50 ) and "
        "latest sma( close, 50 ) > latest sma( close, 200 ) and "
        "( latest max( 20, high ) - latest min( 20, low ) ) / latest min( 20, low ) <= 0.15 and "
        "latest volume < latest sma( volume, 20 ) * 0.8 "
        ") )"
    ),
}


@dataclass
class ChartinkRow:
    nse_code: str
    name: str
    price: float
    pct_change: float
    volume: int
    scan_name: str

    def to_dict(self):
        return {
            "symbol": self.nse_code,
            "name": self.name,
            "price": self.price,
            "pct_change": self.pct_change,
            "volume": self.volume,
            "scan": self.scan_name,
        }


class ChartinkClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": SCREEN_URL,
        })
        self._csrf: str | None = None

    def _get_csrf(self) -> str:
        if self._csrf:
            return self._csrf
        r = self.session.get(SCREEN_URL, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        meta = soup.find("meta", attrs={"name": "csrf-token"})
        if not meta or not meta.get("content"):
            raise RuntimeError("Could not extract CSRF token from Chartink")
        self._csrf = meta["content"]
        return self._csrf

    def run_scan(self, scan_name: str, scan_clause: str) -> List[ChartinkRow]:
        token = self._get_csrf()
        headers = {"X-CSRF-TOKEN": token}
        # Strip the placeholder marker we used for readability.
        clause = scan_clause.replace("{cash}", "")
        clause = re.sub(r"\s+", " ", clause).strip()
        try:
            r = self.session.post(
                PROCESS_URL,
                headers=headers,
                data={"scan_clause": clause},
                timeout=30,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            log.error("Chartink request failed for '%s': %s", scan_name, e)
            return []

        try:
            payload = r.json()
        except ValueError:
            log.error("Chartink returned non-JSON for '%s'", scan_name)
            return []

        rows = []
        for item in payload.get("data", []):
            try:
                rows.append(ChartinkRow(
                    nse_code=item["nsecode"],
                    name=item.get("name", item["nsecode"]),
                    price=float(item.get("close", 0)),
                    pct_change=float(item.get("per_chg", 0)),
                    volume=int(float(item.get("volume", 0))),
                    scan_name=scan_name,
                ))
            except (KeyError, ValueError, TypeError) as e:
                log.warning("Skipping malformed row in %s: %s", scan_name, e)
        log.info("Chartink scan '%s' returned %d rows", scan_name, len(rows))
        return rows

    def run_all(self) -> List[ChartinkRow]:
        all_rows: List[ChartinkRow] = []
        for name, clause in SCANS.items():
            all_rows.extend(self.run_scan(name, clause))
        return all_rows


def dedupe_keep_best(rows: List[ChartinkRow]) -> List[ChartinkRow]:
    """If a stock appears in multiple scans (a strong signal), keep one row but
    record how many scans flagged it via `scan_name = "scan1+scan2+..."`."""
    by_symbol: Dict[str, ChartinkRow] = {}
    scans_per: Dict[str, List[str]] = {}
    for r in rows:
        scans_per.setdefault(r.nse_code, []).append(r.scan_name)
        if r.nse_code not in by_symbol:
            by_symbol[r.nse_code] = r
    for sym, row in by_symbol.items():
        row.scan_name = "+".join(sorted(set(scans_per[sym])))
    return list(by_symbol.values())

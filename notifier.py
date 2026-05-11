"""
WhatsApp notifier with three providers:

  - callmebot : free, personal use, one-time setup (recommended)
  - twilio    : official, paid, required for business
  - console   : just print (use during development)
"""
from __future__ import annotations

import logging
import urllib.parse
from typing import List

import requests

import config
from analyzer import Pick

log = logging.getLogger(__name__)


def format_message(picks: List[Pick]) -> str:
    if not picks:
        return "📊 *Swing Scanner*\nNo high-probability setups today. Sit out, preserve capital."

    header = (
        "📈 *SWING PICKS — NSE*\n"
        f"Top {len(picks)} setups for 3-10 day hold (target {config.TARGET_PCT_MIN:.0f}-{config.TARGET_PCT_MAX:.0f}%).\n"
        "_Educational only. Not financial advice. Position-size and use the stop._\n"
        "—"
    )
    blocks = [header]
    for i, p in enumerate(picks, 1):
        block = (
            f"\n*{i}. {p.symbol}*  (score {p.score}/100)\n"
            f"   Entry ≈ ₹{p.entry:.2f}\n"
            f"   Stop  : ₹{p.stop_loss:.2f}  ({p.risk_pct:.1f}% risk)\n"
            f"   Target: ₹{p.target_low:.2f} – ₹{p.target_high:.2f}  "
            f"({p.upside_low_pct:.1f}–{p.upside_high_pct:.1f}%)\n"
            f"   R:R ≈ {p.rr}   RSI {p.rsi}\n"
            f"   Setup: {p.scan}"
        )
        if p.notes:
            block += "\n   • " + "\n   • ".join(p.notes[:3])
        blocks.append(block)
    blocks.append(
        "\n—\nRules: enter near open if price > entry-1%. Exit if stop hit on close."
    )
    return "\n".join(blocks)


# ---------- Providers ----------

def _send_callmebot(message: str) -> bool:
    if not config.CALLMEBOT_PHONE or not config.CALLMEBOT_APIKEY:
        log.error("CallMeBot not configured — set CALLMEBOT_PHONE and CALLMEBOT_APIKEY")
        return False
    url = (
        "https://api.callmebot.com/whatsapp.php"
        f"?phone={config.CALLMEBOT_PHONE}"
        f"&text={urllib.parse.quote(message)}"
        f"&apikey={config.CALLMEBOT_APIKEY}"
    )
    try:
        r = requests.get(url, timeout=30)
        ok = r.status_code == 200 and "Message queued" in r.text or "Message Sent" in r.text or r.status_code == 200
        if not ok:
            log.error("CallMeBot HTTP %s: %s", r.status_code, r.text[:200])
        return bool(ok)
    except requests.RequestException as e:
        log.error("CallMeBot send failed: %s", e)
        return False


def _send_twilio(message: str) -> bool:
    try:
        from twilio.rest import Client
    except ImportError:
        log.error("twilio package not installed — `pip install twilio`")
        return False
    if not all([config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN,
                config.TWILIO_FROM, config.TWILIO_TO]):
        log.error("Twilio not fully configured")
        return False
    try:
        client = Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)
        client.messages.create(body=message, from_=config.TWILIO_FROM, to=config.TWILIO_TO)
        return True
    except Exception as e:  # noqa: BLE001
        log.error("Twilio send failed: %s", e)
        return False


def send(message: str) -> bool:
    provider = config.NOTIFIER
    log.info("Dispatching message via '%s' (%d chars)", provider, len(message))
    if provider == "callmebot":
        # CallMeBot caps at ~4096 chars per message; split if needed.
        for chunk in _chunks(message, 3500):
            if not _send_callmebot(chunk):
                return False
        return True
    if provider == "twilio":
        return _send_twilio(message)
    # console fallback
    print(message)
    return True


def _chunks(s: str, n: int):
    if len(s) <= n:
        yield s
        return
    # Split on blank lines, keep blocks intact.
    parts, buf = [], ""
    for block in s.split("\n\n"):
        if len(buf) + len(block) + 2 > n and buf:
            parts.append(buf)
            buf = block
        else:
            buf = (buf + "\n\n" + block) if buf else block
    if buf:
        parts.append(buf)
    yield from parts

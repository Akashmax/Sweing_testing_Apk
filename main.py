"""
Swing-trading scanner — entry point.

Usage:
  python main.py               # run once now (good for cron / Task Scheduler)
  python main.py --schedule    # run daily at RUN_TIME (configured in .env)
  python main.py --dry         # run scan but print to console only, no WhatsApp
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import schedule
from tabulate import tabulate

import config
import notifier
from analyzer import analyze_many
from chartink_scanner import ChartinkClient, dedupe_keep_best


def _setup_logging() -> None:
    log_file = config.LOG_DIR / f"scan_{datetime.now():%Y%m%d}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def run_once(dry: bool = False) -> int:
    log = logging.getLogger("main")
    log.info("=== Swing scan starting ===")

    client = ChartinkClient()
    raw = client.run_all()
    log.info("Total raw hits: %d", len(raw))
    if not raw:
        log.warning("Chartink returned no results from any scan")

    deduped = dedupe_keep_best(raw)
    log.info("After dedupe: %d unique candidates", len(deduped))

    picks = analyze_many(deduped, top_n=config.TOP_N)
    log.info("Picks after technical filter: %d", len(picks))

    # Pretty-print
    if picks:
        rows = [[p.symbol, p.score, f"{p.entry:.2f}", f"{p.stop_loss:.2f}",
                 f"{p.target_low:.2f}-{p.target_high:.2f}", f"{p.rr}",
                 f"{p.rsi}", p.scan] for p in picks]
        print("\n" + tabulate(
            rows,
            headers=["Symbol", "Score", "Entry", "Stop", "Target", "R:R", "RSI", "Scan"],
            tablefmt="github",
        ) + "\n")
    else:
        print("\nNo high-probability swing setups today.\n")

    # Persist a JSON snapshot for audit
    snap = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "raw_count": len(raw),
        "picks": [p.__dict__ for p in picks],
    }
    snap_path = config.CACHE_DIR / f"picks_{datetime.now():%Y%m%d_%H%M}.json"
    Path(snap_path).write_text(json.dumps(snap, indent=2, default=str), encoding="utf-8")
    log.info("Snapshot written: %s", snap_path)

    # Send WhatsApp & Save to TXT
    msg = notifier.format_message(picks)
    
    # Save the text file manually
    txt_path = Path("stock_picks.txt")
    txt_path.write_text(msg, encoding="utf-8")
    log.info("Saved text output to %s", txt_path.absolute())

    if dry:
        log.info("Dry-run — printing message instead of sending")
        print("\n" + msg + "\n")
    else:
        ok = notifier.send(msg)
        log.info("Notifier returned %s", ok)
    log.info("=== Swing scan finished ===")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--schedule", action="store_true",
                        help=f"Run daily at {config.RUN_TIME} IST")
    parser.add_argument("--dry", action="store_true",
                        help="Skip WhatsApp send, just print")
    args = parser.parse_args()

    _setup_logging()

    if args.schedule:
        schedule.every().monday.at(config.RUN_TIME).do(run_once, dry=args.dry)
        schedule.every().tuesday.at(config.RUN_TIME).do(run_once, dry=args.dry)
        schedule.every().wednesday.at(config.RUN_TIME).do(run_once, dry=args.dry)
        schedule.every().thursday.at(config.RUN_TIME).do(run_once, dry=args.dry)
        schedule.every().friday.at(config.RUN_TIME).do(run_once, dry=args.dry)
        print(f"Scheduler started. Will run Mon-Fri at {config.RUN_TIME}. Ctrl+C to stop.")
        while True:
            schedule.run_pending()
            time.sleep(30)
    else:
        sys.exit(run_once(dry=args.dry))


if __name__ == "__main__":
    main()

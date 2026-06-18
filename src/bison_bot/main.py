from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

from bison_bot.scanner import Scanner
from bison_bot.utils import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bithumb KRW Bison-style alert bot")
    parser.add_argument("--once", action="store_true", help="Run one scan and exit")
    parser.add_argument("--dry-run", action="store_true", help="Print Telegram messages only")
    parser.add_argument("--config", default="config.yml", help="Path to config.yml")
    parser.add_argument("--max-symbols", type=int, default=None, help="Limit light scan rows locally")
    parser.add_argument(
        "--max-deep-symbols",
        type=int,
        default=None,
        help="Limit candle deep scan symbols locally",
    )
    parser.add_argument("--skip-telegram", action="store_true", help="Do not send or print alerts")
    parser.add_argument("--http-timeout", type=float, default=None, help="HTTP timeout in seconds")
    parser.add_argument(
        "--max-runtime-seconds",
        type=float,
        default=None,
        help="Stop scanning after this many seconds",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logs")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)
    load_dotenv()

    if not args.once:
        raise SystemExit("Only --once mode is supported. Scheduling is handled by GitHub Actions.")

    config_path = Path(args.config).resolve()
    scanner = Scanner(
        config_path=config_path,
        dry_run=args.dry_run,
        max_symbols=args.max_symbols,
        max_deep_symbols=args.max_deep_symbols,
        skip_telegram=args.skip_telegram,
        http_timeout=args.http_timeout,
        max_runtime_seconds=args.max_runtime_seconds,
    )
    scanner.run_once()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

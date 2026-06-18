from __future__ import annotations

import time
from collections import Counter
from pathlib import Path

import pandas as pd

from bison_bot.bison_playbook import analyze_symbol, build_btc_context
from bison_bot.bithumb import BithumbClient
from bison_bot.models import AppConfig, BtcContext, LightScanResult, PortfolioData, Signal
from bison_bot.portfolio import load_portfolio
from bison_bot.state import AlertState
from bison_bot.telegram import TelegramClient, format_signal_message, format_summary_message
from bison_bot.utils import get_logger, load_yaml, unique_preserve_order


class Scanner:
    def __init__(
        self,
        config_path: Path,
        dry_run: bool = False,
        client: BithumbClient | None = None,
        max_symbols: int | None = None,
        max_deep_symbols: int | None = None,
        skip_telegram: bool = False,
        http_timeout: float | None = None,
        max_runtime_seconds: float | None = None,
    ) -> None:
        self.root = config_path.parent
        self.config = AppConfig.from_dict(load_yaml(config_path))
        timeout = http_timeout or self.config.scan.http_timeout_seconds
        self.client = client or BithumbClient(
            sleep_seconds=self.config.scan.request_sleep_seconds,
            timeout=timeout,
        )
        self.dry_run = dry_run
        self.max_symbols = max_symbols
        self.max_deep_symbols = max_deep_symbols
        self.skip_telegram = skip_telegram
        self.max_runtime_seconds = max_runtime_seconds or self.config.scan.max_runtime_seconds
        self.telegram = TelegramClient(dry_run=dry_run)
        self.state = AlertState(self.root / "state" / "sent_signals.json")
        self.logger = get_logger("scanner")
        self.started_at = 0.0

    def run_once(self) -> list[Signal]:
        self.started_at = time.monotonic()
        portfolio = load_portfolio(self.config, self.root)
        light_results = self.client.get_all_krw_tickers()
        light_results = self._limit_light_results(light_results)
        light_by_symbol = {result.symbol: result for result in light_results}
        deep_symbols = self.select_deep_scan_symbols(light_results, portfolio)
        if self.max_deep_symbols is not None and self.max_deep_symbols > 0:
            deep_symbols = deep_symbols[: self.max_deep_symbols]
        btc_context = self._btc_context(light_by_symbol)

        signals: list[Signal] = []
        portfolio_by_symbol = portfolio.by_symbol() if portfolio.enabled else {}

        for symbol in deep_symbols:
            if self._runtime_exceeded():
                self.logger.warning("Max runtime reached before %s; ending this scan early", symbol)
                break
            light = light_by_symbol.get(symbol)
            if light is None:
                self.logger.info("Skipping %s: no light scan row", symbol)
                continue
            candle_map = self._fetch_candles(symbol)
            if not candle_map:
                continue
            try:
                signal = analyze_symbol(
                    light,
                    candle_map,
                    self.config,
                    btc_context=btc_context,
                    holding=portfolio_by_symbol.get(symbol),
                )
            except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the scan.
                self.logger.warning("Skipping %s after analysis error: %s", symbol, exc)
                continue
            signals.append(signal)

        self._send_signals(signals, len(light_results), len(deep_symbols))
        self.state.save()
        return signals

    def _limit_light_results(self, light_results: list[LightScanResult]) -> list[LightScanResult]:
        if self.max_symbols is None or self.max_symbols <= 0:
            return light_results
        by_value = sorted(light_results, key=lambda item: item.trade_value_24h, reverse=True)
        limited = by_value[: self.max_symbols]
        self.logger.info(
            "Local limit active: using %s/%s light scan symbols",
            len(limited),
            len(light_results),
        )
        return limited

    def select_deep_scan_symbols(
        self,
        light_results: list[LightScanResult],
        portfolio: PortfolioData,
    ) -> list[str]:
        by_value = sorted(light_results, key=lambda item: item.trade_value_24h, reverse=True)
        symbols: list[str] = []

        top_n = self.config.scan.deep_scan_trade_value_top_n
        symbols.extend(item.symbol for item in by_value[:top_n])

        for result in light_results:
            if _light_buy_or_bid_candidate(result, self.config):
                symbols.append(result.symbol)

        symbols.extend(self.config.always_include)
        if portfolio.enabled:
            symbols.extend(portfolio.symbols())
        symbols.extend(self.config.manual_risk_symbols)

        if self.config.scan.rotate_universe_batches:
            already = set(unique_preserve_order(symbols))
            remaining = [item.symbol for item in by_value if item.symbol not in already]
            symbols.extend(self.state.rotation_slice(remaining, self.config.scan.rotate_batch_size))

        unique = unique_preserve_order(symbols)
        limit = self.config.scan.deep_scan_candidate_limit
        return unique[:limit] if limit > 0 else unique

    def _btc_context(self, light_by_symbol: dict[str, LightScanResult]) -> BtcContext:
        if self._runtime_exceeded():
            return BtcContext()
        btc_light = light_by_symbol.get("BTC")
        if btc_light is None:
            return BtcContext()
        try:
            htf = self.client.get_candles("BTC", self.config.scan.intervals.htf)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("BTC context skipped: %s", exc)
            return BtcContext()
        return build_btc_context(btc_light, htf)

    def _fetch_candles(self, symbol: str) -> dict[str, pd.DataFrame]:
        candle_map: dict[str, pd.DataFrame] = {}
        for interval in {
            self.config.scan.intervals.fast,
            self.config.scan.intervals.confirm,
            self.config.scan.intervals.htf,
        }:
            if self._runtime_exceeded():
                self.logger.warning("Max runtime reached while fetching %s", symbol)
                return {}
            try:
                candles = self.client.get_candles(symbol, interval)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("Skipping %s %s candles: %s", symbol, interval, exc)
                return {}
            if candles.empty:
                self.logger.info("Skipping %s: empty %s candles", symbol, interval)
                return {}
            candle_map[interval] = candles
        return candle_map

    def _send_signals(self, signals: list[Signal], total_symbols: int, deep_symbols: int) -> None:
        grade_counts = Counter(signal.grade for signal in signals)
        if self.skip_telegram:
            print(
                "Telegram skipped. "
                f"light={total_symbols}, deep={deep_symbols}, analyzed={len(signals)}, "
                f"grades={dict(sorted(grade_counts.items()))}"
            )
            return

        notify_set = set(self.config.alerts.notify_grades)
        summary_set = set(self.config.alerts.summary_grades)
        max_alerts = self.config.alerts.max_alerts_per_run

        notified = 0
        for signal in _rank_signals(signals):
            if signal.grade not in notify_set:
                continue
            if notified >= max_alerts:
                break
            if self.state.is_duplicate(signal, self.config.alerts.duplicate_suppression_hours):
                continue
            delivered = self.telegram.send_message(format_signal_message(signal))
            if delivered:
                self.state.record(signal)
            notified += 1

        summary_signals = [signal for signal in _rank_signals(signals) if signal.grade in summary_set]
        if self.config.alerts.send_full_scan_summary:
            self.telegram.send_message(
                format_summary_message(total_symbols, deep_symbols, dict(grade_counts), summary_signals)
            )
        elif notified == 0 and self.config.alerts.send_no_signal_heartbeat:
            self.telegram.send_message("No BUY_NOW/BID signal. 최종 판단은 사용자 몫.")

    def _runtime_exceeded(self) -> bool:
        if self.max_runtime_seconds is None or self.max_runtime_seconds <= 0:
            return False
        if self.started_at <= 0:
            return False
        return time.monotonic() - self.started_at >= self.max_runtime_seconds


def _light_buy_or_bid_candidate(result: LightScanResult, config: AppConfig) -> bool:
    if result.trade_value_24h < config.liquidity.min_trade_value_krw_for_watch:
        return False
    if result.range_position <= 0.35:
        return True
    if "sharp_drop_24h" in result.tags and result.range_position <= 0.55:
        return True
    return "liquid" in result.tags and result.range_position <= 0.5


def _rank_signals(signals: list[Signal]) -> list[Signal]:
    grade_order = {
        "BUY_NOW_A": 0,
        "BUY_NOW_B": 1,
        "BUY_NOW_C": 2,
        "BID": 3,
        "CONFIRM": 4,
        "TAKE_PROFIT": 5,
        "CUT_REDUCE": 6,
        "HOLD": 7,
        "AVOID": 8,
    }
    return sorted(signals, key=lambda signal: (grade_order.get(signal.grade, 99), -signal.score))

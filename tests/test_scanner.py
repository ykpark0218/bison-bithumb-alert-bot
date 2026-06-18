from __future__ import annotations

from pathlib import Path

import pandas as pd

from bison_bot.models import LightScanResult
from bison_bot.scanner import Scanner


def _frame() -> pd.DataFrame:
    start = pd.Timestamp("2020-01-01 09:00:00")
    rows = []
    for index in range(25):
        base = 100 + index * 0.1
        rows.append(
            {
                "timestamp": start + pd.Timedelta(minutes=5 * index),
                "open": base,
                "high": base + 2,
                "low": base - 2,
                "close": base + 1,
                "volume": 1000 + index,
            }
        )
    return pd.DataFrame(rows)


class FakeBithumbClient:
    def __init__(self) -> None:
        self.candle_calls: list[tuple[str, str]] = []

    def get_all_krw_tickers(self) -> list[LightScanResult]:
        return [
            LightScanResult(
                symbol="BTC",
                current_price=100,
                high_24h=120,
                low_24h=80,
                trade_value_24h=3_000_000_000,
                change_rate_24h=1,
                range_position=0.5,
            ),
            LightScanResult(
                symbol="XRP",
                current_price=50,
                high_24h=80,
                low_24h=45,
                trade_value_24h=2_000_000_000,
                change_rate_24h=-2,
                range_position=0.14,
            ),
            LightScanResult(
                symbol="LOW",
                current_price=10,
                high_24h=20,
                low_24h=9,
                trade_value_24h=5_000_000,
                change_rate_24h=0,
                range_position=0.09,
            ),
        ]

    def get_candles(self, symbol: str, interval: str) -> pd.DataFrame:
        self.candle_calls.append((symbol, interval))
        return _frame()


class FakeState:
    def rotation_slice(self, symbols: list[str], batch_size: int) -> list[str]:
        return symbols[:batch_size]

    def is_duplicate(self, signal, suppression_hours: int) -> bool:
        return False

    def record(self, signal) -> None:
        return None

    def save(self) -> None:
        return None


def test_scanner_uses_fake_client_and_deep_limit() -> None:
    config_path = Path("tests/fixtures/scanner_config.yml")
    fake_client = FakeBithumbClient()

    scanner = Scanner(
        config_path=config_path,
        client=fake_client,  # type: ignore[arg-type]
        dry_run=True,
        max_symbols=2,
        max_deep_symbols=1,
        skip_telegram=True,
    )
    scanner.state = FakeState()  # type: ignore[assignment]
    signals = scanner.run_once()

    assert len(signals) <= 1
    analyzed_symbols = {symbol for symbol, _interval in fake_client.candle_calls}
    assert analyzed_symbols <= {"BTC"}

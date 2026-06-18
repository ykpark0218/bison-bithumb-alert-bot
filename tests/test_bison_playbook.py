from __future__ import annotations

import pandas as pd

from bison_bot.bison_playbook import analyze_portfolio_holding, analyze_symbol
from bison_bot.models import AppConfig, LightScanResult, PortfolioHolding
from bison_bot.portfolio import load_portfolio


def _config() -> AppConfig:
    return AppConfig(
        liquidity={
            "min_trade_value_krw_for_buy_signal": 100_000_000,
            "min_trade_value_krw_for_watch": 10_000_000,
        },
        manual_risk_symbols={
            "H": {
                "reason": "사건성 변동성",
                "allow_buy_signal": False,
                "still_analyze": True,
            }
        },
    )


def _frame(rows: list[tuple[float, float, float, float, float]]) -> pd.DataFrame:
    start = pd.Timestamp("2026-06-18 09:00:00")
    return pd.DataFrame(
        [
            {
                "timestamp": start + pd.Timedelta(minutes=5 * index),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
            for index, (open_, high, low, close, volume) in enumerate(rows)
        ]
    )


def _htf_bullish() -> pd.DataFrame:
    rows = []
    for index in range(40):
        base = 90 + index * 0.5
        rows.append((base, base + 15, base - 2, base + 5, 1000 + index))
    return _frame(rows)


def _htf_bearish() -> pd.DataFrame:
    rows = []
    for index in range(40):
        base = 130 - index * 0.5
        rows.append((base, base + 2, base - 15, base - 5, 1000 + index))
    return _frame(rows)


def _bullish_candles() -> dict[str, pd.DataFrame]:
    fast_rows = [(101, 102, 100, 101.2, 1000)] * 24
    fast_rows.append((101, 105, 99, 104, 3000))
    confirm_rows = [(101, 102, 100, 101, 900)] * 24
    confirm_rows.append((100.5, 103, 99, 102, 2500))
    return {
        "5m": _frame(fast_rows),
        "15m": _frame(confirm_rows),
        "1h": _htf_bullish(),
    }


def _light(
    symbol: str = "PUFFER",
    current: float = 104,
    low: float = 100,
    high: float = 120,
    trade_value: float = 1_000_000_000,
    change_rate: float = 2,
) -> LightScanResult:
    return LightScanResult(
        symbol=symbol,
        current_price=current,
        low_24h=low,
        high_24h=high,
        trade_value_24h=trade_value,
        change_rate_24h=change_rate,
        range_position=(current - low) / (high - low),
        tags=[],
    )


def test_high_chase_is_not_buy_now() -> None:
    light = _light(current=118, low=80, high=120, change_rate=35)
    signal = analyze_symbol(light, _bullish_candles(), _config())

    assert not signal.is_buy_now()
    assert signal.grade in {"CONFIRM", "AVOID"}


def test_low_sweep_recovery_can_be_buy_now_b_or_c() -> None:
    signal = analyze_symbol(_light(), _bullish_candles(), _config())

    assert signal.grade in {"BUY_NOW_A", "BUY_NOW_B", "BUY_NOW_C"}


def test_low_reward_risk_downgrades_from_buy_now() -> None:
    light = _light(current=104, low=100, high=107)
    signal = analyze_symbol(light, _bullish_candles(), _config())

    assert not signal.is_buy_now()
    assert signal.grade in {"BID", "CONFIRM", "AVOID"}


def test_manual_risk_symbol_blocks_buy_now() -> None:
    signal = analyze_symbol(_light(symbol="H"), _bullish_candles(), _config())

    assert not signal.is_buy_now()
    assert signal.grade == "AVOID"


def test_portfolio_disabled_does_not_read_env_or_file(monkeypatch) -> None:
    monkeypatch.setenv("PORTFOLIO_YAML_BASE64", "not-valid-base64")
    config = _config()
    config.portfolio.enabled = False

    portfolio = load_portfolio(config)

    assert portfolio.enabled is False
    assert portfolio.holdings == []


def test_portfolio_loss_has_no_averaging_down_text() -> None:
    config = _config()
    config.portfolio.enabled = True
    holding = PortfolioHolding(symbol="ENA", avg_price=100, quantity=1)
    light = _light(symbol="ENA", current=90, low=85, high=120)
    candles = {"5m": _frame([(90, 91, 89, 90, 1000)] * 25), "15m": _frame([(90, 91, 89, 90, 1000)] * 25), "1h": _htf_bearish()}

    signal = analyze_portfolio_holding(holding, light, candles, config)

    assert signal.grade == "CUT_REDUCE"
    assert any("물타기 금지" in item for item in signal.strategy)


def test_portfolio_profit_near_24h_high_is_take_profit() -> None:
    config = _config()
    config.portfolio.enabled = True
    holding = PortfolioHolding(symbol="ENA", avg_price=100, quantity=1)
    light = _light(symbol="ENA", current=118, low=80, high=120)
    candles = {"5m": _frame([(118, 119, 117, 118, 1000)] * 25), "15m": _frame([(118, 119, 117, 118, 1000)] * 25), "1h": _htf_bullish()}

    signal = analyze_portfolio_holding(holding, light, candles, config)

    assert signal.grade == "TAKE_PROFIT"

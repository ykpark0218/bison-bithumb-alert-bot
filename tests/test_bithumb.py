from __future__ import annotations

from typing import Any

from bison_bot.bithumb import BithumbClient


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


def test_bithumb_client_uses_timeout_and_parses_ticker(monkeypatch) -> None:
    seen: dict[str, Any] = {}
    client = BithumbClient(sleep_seconds=0, timeout=3.5)

    def fake_get(url: str, timeout: float) -> FakeResponse:
        seen["url"] = url
        seen["timeout"] = timeout
        return FakeResponse(
            {
                "status": "0000",
                "data": {
                    "BTC": {
                        "closing_price": "100",
                        "max_price": "120",
                        "min_price": "80",
                        "acc_trade_value_24H": "1000000000",
                        "fluctate_rate_24H": "5",
                    },
                    "date": "0",
                },
            }
        )

    monkeypatch.setattr(client.session, "get", fake_get)

    results = client.get_all_krw_tickers()

    assert seen["timeout"] == 3.5
    assert seen["url"].endswith("/public/ticker/ALL_KRW")
    assert len(results) == 1
    assert results[0].symbol == "BTC"
    assert results[0].range_position == 0.5


def test_bithumb_client_parses_mock_candles(monkeypatch) -> None:
    client = BithumbClient(sleep_seconds=0, timeout=2)

    def fake_get(url: str, timeout: float) -> FakeResponse:
        assert timeout == 2
        assert url.endswith("/public/candlestick/BTC_KRW/5m")
        return FakeResponse(
            {
                "status": "0000",
                "data": [
                    [1_609_459_200_000, "100", "101", "102", "99", "10"],
                    [1_609_459_500_000, "101", "103", "104", "100", "12"],
                ],
            }
        )

    monkeypatch.setattr(client.session, "get", fake_get)

    candles = client.get_candles("BTC", "5m")

    assert list(candles.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert len(candles) == 2
    assert candles.iloc[-1]["close"] == 103

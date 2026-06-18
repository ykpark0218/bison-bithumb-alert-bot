from __future__ import annotations

from typing import Any

from bison_bot.bithumb import BithumbClient, candle_endpoint, normalize_market


class FakeResponse:
    def __init__(self, payload: Any, url: str = "https://api.bithumb.com/mock") -> None:
        self.payload = payload
        self.url = url
        self.status_code = 200
        self.text = ""

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


def test_bithumb_client_uses_timeout_and_parses_ticker(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []
    client = BithumbClient(sleep_seconds=0, timeout=3.5)

    def fake_get(
        url: str,
        params: dict[str, str | int] | None = None,
        timeout: float | None = None,
    ) -> FakeResponse:
        calls.append({"url": url, "params": params, "timeout": timeout})
        if url.endswith("/v1/market/all"):
            return FakeResponse(
                [
                    {"market": "KRW-BTC", "korean_name": "비트코인"},
                    {"market": "BTC-ETH", "korean_name": "이더리움"},
                ],
                url=url,
            )
        if url.endswith("/v1/ticker"):
            assert params == {"markets": "KRW-BTC"}
            return FakeResponse(
                [
                    {
                        "market": "KRW-BTC",
                        "trade_price": 100,
                        "opening_price": 95,
                        "high_price": 120,
                        "low_price": 80,
                        "acc_trade_price_24h": 1_000_000_000,
                        "signed_change_rate": 0.05,
                    }
                ],
                url=url,
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(client.session, "get", fake_get)

    results = client.get_all_krw_tickers()

    assert all(call["timeout"] == 3.5 for call in calls)
    assert calls[0]["url"].endswith("/v1/market/all")
    assert calls[1]["url"].endswith("/v1/ticker")
    assert len(results) == 1
    assert results[0].symbol == "BTC"
    assert results[0].market == "KRW-BTC"
    assert results[0].base_symbol == "BTC"
    assert results[0].range_position == 0.5
    assert results[0].change_rate_24h == 5.0


def test_bithumb_client_parses_mock_candles(monkeypatch) -> None:
    client = BithumbClient(sleep_seconds=0, timeout=2)

    def fake_get(
        url: str,
        params: dict[str, str | int] | None = None,
        timeout: float | None = None,
    ) -> FakeResponse:
        assert timeout == 2
        assert url.endswith("/v1/candles/minutes/5")
        assert params == {"market": "KRW-BTC", "count": 200}
        return FakeResponse(
            [
                {
                    "market": "KRW-BTC",
                    "candle_date_time_kst": "2021-01-01T09:05:00",
                    "opening_price": 101,
                    "high_price": 104,
                    "low_price": 100,
                    "trade_price": 103,
                    "candle_acc_trade_volume": 12,
                },
                {
                    "market": "KRW-BTC",
                    "candle_date_time_kst": "2021-01-01T09:00:00",
                    "opening_price": 100,
                    "high_price": 102,
                    "low_price": 99,
                    "trade_price": 101,
                    "candle_acc_trade_volume": 10,
                },
            ],
            url=url,
        )

    monkeypatch.setattr(client.session, "get", fake_get)

    candles = client.get_candles("BTC", "5m")

    assert list(candles.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert len(candles) == 2
    assert candles.iloc[-1]["close"] == 103


def test_market_and_candle_endpoint_helpers() -> None:
    assert normalize_market("BTC") == "KRW-BTC"
    assert normalize_market("KRW-ETH") == "KRW-ETH"
    assert candle_endpoint("KRW-BTC", "1h") == (
        "/v1/candles/minutes/60",
        {"market": "KRW-BTC", "count": 200},
    )

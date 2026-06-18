from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

import pandas as pd
import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from bison_bot.models import LightScanResult
from bison_bot.rules import remove_open_candle
from bison_bot.utils import calculate_range_position, get_logger, safe_float

BASE_URL = "https://api.bithumb.com"
MAX_TICKER_BATCH_SIZE = 50
CANDLE_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


class BithumbPublicApiError(RuntimeError):
    """Raised when the public API response cannot be used."""


class BithumbClient:
    def __init__(self, sleep_seconds: float = 0.12, timeout: float = 10.0) -> None:
        self.sleep_seconds = sleep_seconds
        self.timeout = timeout
        self.session = requests.Session()
        self.logger = get_logger("bithumb")

    @retry(
        retry=retry_if_exception_type((requests.RequestException, BithumbPublicApiError)),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _get_json(self, path: str, params: dict[str, str | int] | None = None) -> Any:
        url = f"{BASE_URL}{path}"
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
        except requests.HTTPError as exc:
            response = exc.response
            status = response.status_code if response is not None else "unknown"
            body = response.text[:300] if response is not None else ""
            response_url = response.url if response is not None else url
            raise BithumbPublicApiError(
                f"Bithumb public API HTTP {status}: {response_url}. "
                f"Endpoint={path}. Response={body!r}"
            ) from exc
        payload = response.json()
        if isinstance(payload, dict):
            status = str(payload.get("status", ""))
            if status and status != "0000":
                raise BithumbPublicApiError(
                    f"Bithumb public API status={status}: {response.url}. Endpoint={path}"
                )
        return payload

    def get_all_krw_tickers(self) -> list[LightScanResult]:
        markets = self.get_krw_markets()
        if not markets:
            self.logger.warning("No KRW markets returned from Bithumb v1 market/all")
            return []

        results: list[LightScanResult] = []
        for market_batch in _chunks(markets, MAX_TICKER_BATCH_SIZE):
            payload = self._get_json(
                "/v1/ticker",
                params={"markets": ",".join(market_batch)},
            )
            if not isinstance(payload, list):
                self.logger.warning("Skipping ticker batch: unexpected payload type")
                continue
            for row in payload:
                if not isinstance(row, dict):
                    continue
                parsed = self._parse_ticker_row(row)
                if parsed is not None:
                    results.append(parsed)
            time.sleep(self.sleep_seconds)
        return results

    def get_krw_markets(self) -> list[str]:
        payload = self._get_json("/v1/market/all")
        if not isinstance(payload, list):
            raise BithumbPublicApiError("/v1/market/all response is not a list")

        markets: list[str] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            market = str(row.get("market", "")).upper()
            if market.startswith("KRW-"):
                markets.append(market)
        return markets

    def _parse_ticker_row(self, row: dict[str, Any]) -> LightScanResult | None:
        market = str(row.get("market", "")).upper()
        base_symbol = market.split("-", 1)[1] if market.startswith("KRW-") else market
        if not market or not base_symbol:
            self.logger.warning("Skipping ticker row: missing market field")
            return None

        current = safe_float(row.get("trade_price") or row.get("close"))
        high = safe_float(row.get("high_price"))
        low = safe_float(row.get("low_price"))
        if current is None or high is None or low is None or current <= 0 or high <= 0 or low <= 0:
            self.logger.warning("Skipping %s: invalid price fields in ticker row", market)
            return None

        trade_value = safe_float(
            row.get("acc_trade_price_24h")
            or row.get("acc_trade_price_24H")
            or row.get("trade_value_24h"),
            0.0,
        ) or 0.0

        change_rate = safe_float(
            row.get("change_rate")
            or row.get("signed_change_rate"),
            0.0,
        )
        if change_rate is not None and abs(change_rate) <= 1:
            change_rate *= 100

        range_pos = calculate_range_position(current, low, high)
        tags = tag_light_scan(range_pos, change_rate or 0.0, trade_value or 0.0)

        return LightScanResult(
            symbol=base_symbol,
            market=market,
            base_symbol=base_symbol,
            current_price=current,
            high_24h=high,
            low_24h=low,
            trade_value_24h=trade_value or 0.0,
            change_rate_24h=change_rate or 0.0,
            range_position=range_pos,
            tags=tags,
        )

    def get_candles(self, symbol: str, interval: str) -> pd.DataFrame:
        market = normalize_market(symbol)
        path, params = candle_endpoint(market, interval)
        payload = self._get_json(path, params=params)
        if not isinstance(payload, list) or not payload:
            self.logger.warning("Skipping %s %s: empty candlestick data", symbol, interval)
            return pd.DataFrame(columns=CANDLE_COLUMNS)

        rows: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "timestamp": item.get("candle_date_time_kst")
                    or item.get("candle_date_time_utc"),
                    "open": item.get("opening_price"),
                    "high": item.get("high_price"),
                    "low": item.get("low_price"),
                    "close": item.get("trade_price"),
                    "volume": item.get("candle_acc_trade_volume")
                    or item.get("acc_trade_volume"),
                }
            )

        if not rows:
            self.logger.warning("Skipping %s %s: no usable candle rows", symbol, interval)
            return pd.DataFrame(columns=CANDLE_COLUMNS)

        frame = pd.DataFrame(rows)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
        frame = frame.dropna(subset=["timestamp"])
        if frame.empty:
            return pd.DataFrame(columns=CANDLE_COLUMNS)

        if getattr(frame["timestamp"].dt, "tz", None) is not None:
            frame["timestamp"] = frame["timestamp"].dt.tz_convert("Asia/Seoul").dt.tz_localize(None)
        for column in ["open", "high", "low", "close", "volume"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

        frame = frame.dropna(subset=CANDLE_COLUMNS)
        frame = frame[CANDLE_COLUMNS].sort_values("timestamp")
        time.sleep(self.sleep_seconds)
        return remove_open_candle(frame, interval)


def normalize_market(symbol_or_market: str) -> str:
    value = symbol_or_market.upper().strip()
    if value.startswith("KRW-"):
        return value
    return f"KRW-{value}"


def candle_endpoint(market: str, interval: str) -> tuple[str, dict[str, str | int]]:
    if interval == "5m":
        return "/v1/candles/minutes/5", {"market": market, "count": 200}
    if interval == "15m":
        return "/v1/candles/minutes/15", {"market": market, "count": 200}
    if interval == "1h":
        return "/v1/candles/minutes/60", {"market": market, "count": 200}
    if interval in {"1d", "24h"}:
        return "/v1/candles/days", {"market": market, "count": 200}
    raise ValueError(f"Unsupported Bithumb v1 candle interval: {interval}")


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def tag_light_scan(range_position: float, change_rate: float, trade_value: float) -> list[str]:
    tags: list[str] = []
    if range_position >= 0.85:
        tags.append("high_chase_zone")
    elif range_position <= 0.2:
        tags.append("low_zone")
    else:
        tags.append("mid_zone")

    if change_rate >= 15:
        tags.append("strong_rise_24h")
    elif change_rate <= -12:
        tags.append("sharp_drop_24h")

    if trade_value < 50_000_000:
        tags.append("low_liquidity")
    elif trade_value >= 500_000_000:
        tags.append("liquid")

    if abs(change_rate) >= 25:
        tags.append("event_risk")
    return tags

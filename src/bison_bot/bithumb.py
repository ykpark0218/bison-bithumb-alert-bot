from __future__ import annotations

import time
from typing import Any

import pandas as pd
import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from bison_bot.models import LightScanResult
from bison_bot.rules import remove_open_candle
from bison_bot.utils import calculate_range_position, get_logger, safe_float

BASE_URL = "https://api.bithumb.com"


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
    def _get_json(self, path: str) -> dict[str, Any]:
        url = f"{BASE_URL}{path}"
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise BithumbPublicApiError(f"Unexpected payload type from {url}")
        status = str(payload.get("status", ""))
        if status and status != "0000":
            raise BithumbPublicApiError(f"Bithumb status={status} from {url}")
        return payload

    def get_all_krw_tickers(self) -> list[LightScanResult]:
        payload = self._get_json("/public/ticker/ALL_KRW")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise BithumbPublicApiError("ALL_KRW response missing data mapping")

        results: list[LightScanResult] = []
        for symbol, row in data.items():
            if symbol.lower() == "date":
                continue
            if not isinstance(row, dict):
                self.logger.warning("Skipping %s: ticker row is not a mapping", symbol)
                continue

            parsed = self._parse_ticker_row(symbol, row)
            if parsed is not None:
                results.append(parsed)
        return results

    def _parse_ticker_row(self, symbol: str, row: dict[str, Any]) -> LightScanResult | None:
        current = safe_float(
            row.get("closing_price")
            or row.get("close")
            or row.get("trade_price")
            or row.get("prev_closing_price")
        )
        high = safe_float(row.get("max_price") or row.get("high_price"))
        low = safe_float(row.get("min_price") or row.get("low_price"))
        if current is None or high is None or low is None or current <= 0 or high <= 0 or low <= 0:
            self.logger.warning("Skipping %s: invalid price fields in ticker row", symbol)
            return None

        units = safe_float(row.get("units_traded_24H") or row.get("units_traded"), 0.0) or 0.0
        trade_value = safe_float(
            row.get("acc_trade_value_24H")
            or row.get("acc_trade_value")
            or row.get("trade_value")
            or row.get("value"),
            0.0,
        )
        if not trade_value:
            trade_value = current * units

        change_rate = safe_float(
            row.get("fluctate_rate_24H")
            or row.get("fluctate_rate")
            or row.get("signed_change_rate"),
            0.0,
        )
        if change_rate is not None and abs(change_rate) <= 1:
            change_rate *= 100

        range_pos = calculate_range_position(current, low, high)
        tags = tag_light_scan(range_pos, change_rate or 0.0, trade_value or 0.0)

        return LightScanResult(
            symbol=symbol.upper(),
            current_price=current,
            high_24h=high,
            low_24h=low,
            trade_value_24h=trade_value or 0.0,
            change_rate_24h=change_rate or 0.0,
            range_position=range_pos,
            tags=tags,
        )

    def get_candles(self, symbol: str, interval: str) -> pd.DataFrame:
        payload = self._get_json(f"/public/candlestick/{symbol.upper()}_KRW/{interval}")
        data = payload.get("data")
        if not isinstance(data, list) or not data:
            self.logger.warning("Skipping %s %s: empty candlestick data", symbol, interval)
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        rows: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, list | tuple) or len(item) < 6:
                continue
            # Bithumb public candlestick rows are:
            # [timestamp, open, close, high, low, volume]
            rows.append(
                {
                    "timestamp": item[0],
                    "open": item[1],
                    "close": item[2],
                    "high": item[3],
                    "low": item[4],
                    "volume": item[5],
                }
            )

        if not rows:
            self.logger.warning("Skipping %s %s: no usable candle rows", symbol, interval)
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        frame = pd.DataFrame(rows)
        frame["timestamp"] = pd.to_numeric(frame["timestamp"], errors="coerce")
        frame = frame.dropna(subset=["timestamp"])
        if frame.empty:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
        frame["timestamp"] = frame["timestamp"].dt.tz_convert("Asia/Seoul").dt.tz_localize(None)
        for column in ["open", "high", "low", "close", "volume"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

        frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
        frame = frame[["timestamp", "open", "high", "low", "close", "volume"]].sort_values(
            "timestamp"
        )
        time.sleep(self.sleep_seconds)
        return remove_open_candle(frame, interval)


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

from __future__ import annotations

import pandas as pd

from bison_bot.utils import calculate_range_position, reward_risk_ratio

INTERVAL_TO_DELTA = {
    "1m": pd.Timedelta(minutes=1),
    "3m": pd.Timedelta(minutes=3),
    "5m": pd.Timedelta(minutes=5),
    "10m": pd.Timedelta(minutes=10),
    "15m": pd.Timedelta(minutes=15),
    "30m": pd.Timedelta(minutes=30),
    "1h": pd.Timedelta(hours=1),
    "6h": pd.Timedelta(hours=6),
    "12h": pd.Timedelta(hours=12),
    "24h": pd.Timedelta(days=1),
}


def range_position(current: float, low: float, high: float) -> float:
    return calculate_range_position(current, low, high)


def reward_risk(entry: float, invalidation: float, target: float) -> float:
    return reward_risk_ratio(entry, invalidation, target)


def interval_to_timedelta(interval: str) -> pd.Timedelta:
    if interval not in INTERVAL_TO_DELTA:
        raise ValueError(f"Unsupported interval: {interval}")
    return INTERVAL_TO_DELTA[interval]


def normalize_candles(df: pd.DataFrame) -> pd.DataFrame:
    required = ["timestamp", "open", "high", "low", "close", "volume"]
    if df.empty:
        return pd.DataFrame(columns=required)

    normalized = df.copy()
    for column in required:
        if column not in normalized.columns:
            return pd.DataFrame(columns=required)

    normalized["timestamp"] = pd.to_datetime(normalized["timestamp"], errors="coerce")
    for column in ["open", "high", "low", "close", "volume"]:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

    normalized = normalized.dropna(subset=required)
    normalized = normalized.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    return normalized[required].reset_index(drop=True)


def remove_open_candle(
    df: pd.DataFrame,
    interval: str,
    now: pd.Timestamp | str | None = None,
) -> pd.DataFrame:
    candles = normalize_candles(df)
    if candles.empty:
        return candles

    delta = interval_to_timedelta(interval)
    now_ts = pd.Timestamp.now() if now is None else pd.Timestamp(now)
    latest = pd.Timestamp(candles.iloc[-1]["timestamp"])

    if latest.tzinfo is not None and now_ts.tzinfo is None:
        now_ts = now_ts.tz_localize(latest.tzinfo)
    elif latest.tzinfo is None and now_ts.tzinfo is not None:
        now_ts = now_ts.tz_localize(None)

    if latest + delta > now_ts:
        candles = candles.iloc[:-1]
    return candles.reset_index(drop=True)


def average_body(df: pd.DataFrame, lookback: int = 20) -> float:
    candles = normalize_candles(df)
    if candles.empty:
        return 0.0
    sample = candles.tail(lookback)
    return float((sample["close"] - sample["open"]).abs().mean())


def average_volume(df: pd.DataFrame, lookback: int = 20) -> float:
    candles = normalize_candles(df)
    if candles.empty:
        return 0.0
    return float(candles.tail(lookback)["volume"].mean())


def recent_swing_low(df: pd.DataFrame, lookback: int = 20, exclude_last: bool = True) -> float | None:
    candles = normalize_candles(df)
    if len(candles) < 3:
        return None
    sample = candles.iloc[:-1] if exclude_last else candles
    sample = sample.tail(lookback)
    if sample.empty:
        return None
    return float(sample["low"].min())


def recent_swing_high(df: pd.DataFrame, lookback: int = 20, exclude_last: bool = True) -> float | None:
    candles = normalize_candles(df)
    if len(candles) < 3:
        return None
    sample = candles.iloc[:-1] if exclude_last else candles
    sample = sample.tail(lookback)
    if sample.empty:
        return None
    return float(sample["high"].max())


def latest_timestamp(df: pd.DataFrame) -> str:
    candles = normalize_candles(df)
    if candles.empty:
        return ""
    return pd.Timestamp(candles.iloc[-1]["timestamp"]).isoformat()


def detect_bullish_sweep(df: pd.DataFrame, key_level: float | None = None) -> tuple[bool, float | None]:
    candles = normalize_candles(df)
    if len(candles) < 3:
        return False, None

    level = key_level if key_level is not None else recent_swing_low(candles)
    if level is None:
        return False, None

    last = candles.iloc[-1]
    swept = float(last["low"]) < level and float(last["close"]) > level
    return bool(swept), level


def detect_bearish_sweep(df: pd.DataFrame, key_level: float | None = None) -> tuple[bool, float | None]:
    candles = normalize_candles(df)
    if len(candles) < 3:
        return False, None

    level = key_level if key_level is not None else recent_swing_high(candles)
    if level is None:
        return False, None

    last = candles.iloc[-1]
    swept = float(last["high"]) > level and float(last["close"]) < level
    return bool(swept), level


def has_body_recovery(df: pd.DataFrame, key_level: float) -> bool:
    candles = normalize_candles(df)
    if candles.empty:
        return False
    return float(candles.iloc[-1]["close"]) > key_level


def has_body_breakdown(df: pd.DataFrame, key_level: float) -> bool:
    candles = normalize_candles(df)
    if candles.empty:
        return False
    return float(candles.iloc[-1]["close"]) < key_level


def detect_bullish_mss(df: pd.DataFrame, lookback: int = 20) -> tuple[bool, float | None]:
    candles = normalize_candles(df)
    if len(candles) < 3:
        return False, None
    level = recent_swing_high(candles, lookback=lookback)
    if level is None:
        return False, None
    return bool(float(candles.iloc[-1]["close"]) > level), level


def detect_bearish_mss(df: pd.DataFrame, lookback: int = 20) -> tuple[bool, float | None]:
    candles = normalize_candles(df)
    if len(candles) < 3:
        return False, None
    level = recent_swing_low(candles, lookback=lookback)
    if level is None:
        return False, None
    return bool(float(candles.iloc[-1]["close"]) < level), level


def detect_bullish_displacement(
    df: pd.DataFrame,
    key_level: float | None = None,
    lookback: int = 20,
) -> bool:
    candles = normalize_candles(df)
    if len(candles) < 3:
        return False
    last = candles.iloc[-1]
    body = abs(float(last["close"]) - float(last["open"]))
    avg_body = average_body(candles.iloc[:-1], lookback=lookback)
    if avg_body <= 0:
        return False

    level = key_level
    if level is None:
        level = recent_swing_high(candles, lookback=lookback)
    if level is None:
        return False

    return bool(
        float(last["close"]) > float(last["open"])
        and body >= avg_body * 1.5
        and float(last["close"]) > level
    )


def detect_bearish_displacement(
    df: pd.DataFrame,
    key_level: float | None = None,
    lookback: int = 20,
) -> bool:
    candles = normalize_candles(df)
    if len(candles) < 3:
        return False
    last = candles.iloc[-1]
    body = abs(float(last["close"]) - float(last["open"]))
    avg_body = average_body(candles.iloc[:-1], lookback=lookback)
    if avg_body <= 0:
        return False

    level = key_level
    if level is None:
        level = recent_swing_low(candles, lookback=lookback)
    if level is None:
        return False

    return bool(
        float(last["close"]) < float(last["open"])
        and body >= avg_body * 1.5
        and float(last["close"]) < level
    )


def volume_is_expanding(df: pd.DataFrame, lookback: int = 20) -> bool:
    candles = normalize_candles(df)
    if len(candles) < 3:
        return False
    avg = average_volume(candles.iloc[:-1], lookback=lookback)
    if avg <= 0:
        return False
    return bool(float(candles.iloc[-1]["volume"]) > avg)


def detect_fvgs(df: pd.DataFrame, min_gap_ratio: float = 0.001) -> list[dict[str, float | str]]:
    candles = normalize_candles(df)
    fvgs: list[dict[str, float | str]] = []
    if len(candles) < 3:
        return fvgs

    for index in range(2, len(candles)):
        left = candles.iloc[index - 2]
        current = candles.iloc[index]
        close = float(current["close"])
        if close <= 0:
            continue

        bullish_gap = float(current["low"]) - float(left["high"])
        if bullish_gap > 0 and bullish_gap / close >= min_gap_ratio:
            fvgs.append(
                {
                    "type": "bullish",
                    "low": float(left["high"]),
                    "high": float(current["low"]),
                    "timestamp": str(current["timestamp"]),
                }
            )

        bearish_gap = float(left["low"]) - float(current["high"])
        if bearish_gap > 0 and bearish_gap / close >= min_gap_ratio:
            fvgs.append(
                {
                    "type": "bearish",
                    "low": float(current["high"]),
                    "high": float(left["low"]),
                    "timestamp": str(current["timestamp"]),
                }
            )
    return fvgs


def calculate_htf_bias(df: pd.DataFrame, lookback: int = 40) -> str:
    candles = normalize_candles(df).tail(lookback)
    if len(candles) < 12:
        return "neutral"

    midpoint = len(candles) // 2
    first = candles.iloc[:midpoint]
    second = candles.iloc[midpoint:]
    first_high = float(first["high"].max())
    first_low = float(first["low"].min())
    second_high = float(second["high"].max())
    second_low = float(second["low"].min())

    if second_high > first_high and second_low > first_low:
        return "bullish"
    if second_high < first_high and second_low < first_low:
        return "bearish"
    return "neutral"


def premium_discount(df: pd.DataFrame, current_price: float, lookback: int = 60) -> str:
    candles = normalize_candles(df).tail(lookback)
    if len(candles) < 3:
        return "equilibrium"
    high = float(candles["high"].max())
    low = float(candles["low"].min())
    if high <= low:
        return "equilibrium"
    midline = low + (high - low) * 0.5
    if current_price < midline:
        return "discount"
    if current_price > midline:
        return "premium"
    return "equilibrium"

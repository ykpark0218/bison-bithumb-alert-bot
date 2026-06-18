from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

LOGGER_NAME = "bison_bot"


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(LOGGER_NAME if name is None else f"{LOGGER_NAME}.{name}")


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return loaded


def safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        if isinstance(value, str):
            value = value.replace(",", "").strip()
            if value == "":
                return default
        return float(value)
    except (TypeError, ValueError):
        return default


def calculate_range_position(current: float, low: float, high: float) -> float:
    if high <= low:
        return 0.5
    value = (current - low) / (high - low)
    return max(0.0, min(1.0, value))


def reward_risk_ratio(entry: float, invalidation: float, target: float) -> float:
    risk = entry - invalidation
    reward = target - entry
    if risk <= 0 or reward <= 0:
        return 0.0
    return reward / risk


def unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.upper().strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def chunk_text(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > limit and current:
            chunks.append(current.rstrip())
            current = ""
        if len(line) > limit:
            for index in range(0, len(line), limit):
                chunks.append(line[index : index + limit].rstrip())
        else:
            current += line
    if current:
        chunks.append(current.rstrip())
    return chunks


def format_krw(value: float | None) -> str:
    if value is None:
        return "-"
    if value >= 1000:
        return f"{value:,.0f}원"
    if value >= 100:
        return f"{value:,.1f}원"
    if value >= 10:
        return f"{value:,.2f}원"
    return f"{value:,.4f}원"


def format_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}%"

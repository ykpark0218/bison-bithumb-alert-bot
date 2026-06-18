from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

import yaml

from bison_bot.models import AppConfig, PortfolioData, PortfolioHolding
from bison_bot.utils import get_logger


def load_portfolio(config: AppConfig, root: Path | None = None) -> PortfolioData:
    if not config.portfolio.enabled:
        return PortfolioData(enabled=False, holdings=[])

    root = root or Path.cwd()
    logger = get_logger("portfolio")
    portfolio_path = root / "portfolio.yml"

    raw: dict[str, Any] | None = None
    if portfolio_path.exists():
        with portfolio_path.open("r", encoding="utf-8") as file:
            loaded = yaml.safe_load(file) or {}
        if isinstance(loaded, dict):
            raw = loaded
    else:
        encoded = os.getenv("PORTFOLIO_YAML_BASE64", "").strip()
        if encoded:
            try:
                decoded = base64.b64decode(encoded).decode("utf-8")
                loaded = yaml.safe_load(decoded) or {}
                if isinstance(loaded, dict):
                    raw = loaded
            except (ValueError, yaml.YAMLError) as exc:
                logger.warning("Ignoring invalid PORTFOLIO_YAML_BASE64: %s", exc)

    if raw is None:
        logger.info("portfolio.enabled is true but no portfolio data was found")
        return PortfolioData(enabled=True, holdings=[])

    holdings = []
    for item in raw.get("holdings", []):
        if not isinstance(item, dict):
            continue
        try:
            holdings.append(
                PortfolioHolding(
                    symbol=str(item["symbol"]).upper(),
                    avg_price=float(item["avg_price"]),
                    quantity=float(item.get("quantity", 0.0)),
                )
            )
        except (KeyError, TypeError, ValueError):
            logger.warning("Skipping invalid portfolio holding: %s", item)

    return PortfolioData(enabled=True, holdings=holdings)

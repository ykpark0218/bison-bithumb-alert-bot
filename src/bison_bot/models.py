from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Grade = Literal[
    "BUY_NOW_A",
    "BUY_NOW_B",
    "BUY_NOW_C",
    "BID",
    "CONFIRM",
    "HOLD",
    "TAKE_PROFIT",
    "CUT_REDUCE",
    "AVOID",
]


class ScanIntervals(BaseModel):
    fast: str = "5m"
    confirm: str = "15m"
    htf: str = "1h"


class ScanConfig(BaseModel):
    mode: str = "full_universe"
    top_n: int = 0
    deep_scan_trade_value_top_n: int = 80
    deep_scan_candidate_limit: int = 100
    rotate_universe_batches: bool = True
    rotate_batch_size: int = 30
    request_sleep_seconds: float = 0.15
    http_timeout_seconds: float = 10.0
    max_runtime_seconds: float = 240.0
    intervals: ScanIntervals = Field(default_factory=ScanIntervals)


class LiquidityConfig(BaseModel):
    min_trade_value_krw_for_buy_signal: float = 500_000_000
    min_trade_value_krw_for_watch: float = 50_000_000
    allow_low_liquidity_summary: bool = True


class AlertConfig(BaseModel):
    max_alerts_per_run: int = 10
    duplicate_suppression_hours: int = 6
    notify_grades: list[str] = Field(
        default_factory=lambda: ["BUY_NOW_A", "BUY_NOW_B", "BUY_NOW_C", "BID"]
    )
    summary_grades: list[str] = Field(default_factory=lambda: ["CONFIRM", "AVOID"])
    send_no_signal_heartbeat: bool = False
    send_full_scan_summary: bool = True


class RiskConfig(BaseModel):
    max_entry_risk_pct: float = 3.0
    min_reward_risk: float = 1.5
    position_size_hint: bool = True


class PortfolioConfig(BaseModel):
    enabled: bool = False


class ManualRiskSymbol(BaseModel):
    reason: str = ""
    allow_buy_signal: bool = True
    still_analyze: bool = True


class AppConfig(BaseModel):
    market: str = "KRW"
    scan: ScanConfig = Field(default_factory=ScanConfig)
    liquidity: LiquidityConfig = Field(default_factory=LiquidityConfig)
    alerts: AlertConfig = Field(default_factory=AlertConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    portfolio: PortfolioConfig = Field(default_factory=PortfolioConfig)
    always_include: list[str] = Field(default_factory=list)
    manual_risk_symbols: dict[str, ManualRiskSymbol] = Field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        return cls(**data)


class LightScanResult(BaseModel):
    symbol: str
    current_price: float
    high_24h: float
    low_24h: float
    trade_value_24h: float = 0.0
    change_rate_24h: float = 0.0
    range_position: float = 0.5
    tags: list[str] = Field(default_factory=list)


class PortfolioHolding(BaseModel):
    symbol: str
    avg_price: float
    quantity: float = 0.0


class PortfolioData(BaseModel):
    enabled: bool = False
    holdings: list[PortfolioHolding] = Field(default_factory=list)

    def symbols(self) -> list[str]:
        return [holding.symbol.upper() for holding in self.holdings]

    def by_symbol(self) -> dict[str, PortfolioHolding]:
        return {holding.symbol.upper(): holding for holding in self.holdings}


class BtcContext(BaseModel):
    stable: bool = True
    near_24h_low_breakdown: bool = False
    near_24h_high_rejection: bool = False
    bias_1h: str = "neutral"


class Signal(BaseModel):
    symbol: str
    grade: Grade
    score: float = 0.0
    model: str = ""
    current_price: float
    low_24h: float | None = None
    high_24h: float | None = None
    range_position: float | None = None
    entry_price: float | None = None
    bid_low: float | None = None
    bid_high: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    invalidation: float | None = None
    reward_risk: float = 0.0
    key_level: float | None = None
    candle_timestamp: str = ""
    reasons: list[str] = Field(default_factory=list)
    strategy: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    is_portfolio: bool = False

    def is_buy_now(self) -> bool:
        return self.grade in {"BUY_NOW_A", "BUY_NOW_B", "BUY_NOW_C"}

    def signal_id(self) -> str:
        level = "-" if self.key_level is None else f"{self.key_level:.8f}"
        return f"{self.symbol}:{self.grade}:{level}:{self.candle_timestamp}"

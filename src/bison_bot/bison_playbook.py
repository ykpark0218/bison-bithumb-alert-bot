from __future__ import annotations

import math

import pandas as pd

from bison_bot.models import (
    AppConfig,
    BtcContext,
    Grade,
    LightScanResult,
    PortfolioHolding,
    Signal,
)
from bison_bot.rules import (
    calculate_htf_bias,
    detect_bearish_displacement,
    detect_bearish_sweep,
    detect_bullish_displacement,
    detect_bullish_mss,
    detect_bullish_sweep,
    detect_fvgs,
    has_body_recovery,
    latest_timestamp,
    normalize_candles,
    premium_discount,
    recent_swing_high,
    recent_swing_low,
    reward_risk,
    volume_is_expanding,
)
from bison_bot.utils import format_krw


def build_btc_context(
    light: LightScanResult | None,
    htf_candles: pd.DataFrame | None,
) -> BtcContext:
    if light is None or htf_candles is None or htf_candles.empty:
        return BtcContext()

    bias = calculate_htf_bias(htf_candles)
    range_pos = light.range_position
    bearish_sweep, _ = detect_bearish_sweep(htf_candles, light.high_24h)
    breakdown = range_pos <= 0.15 and bias == "bearish"
    high_rejection = range_pos >= 0.85 and bearish_sweep
    return BtcContext(
        stable=not breakdown and not high_rejection,
        near_24h_low_breakdown=breakdown,
        near_24h_high_rejection=high_rejection,
        bias_1h=bias,
    )


def analyze_symbol(
    light: LightScanResult,
    candles: dict[str, pd.DataFrame],
    config: AppConfig,
    btc_context: BtcContext | None = None,
    holding: PortfolioHolding | None = None,
) -> Signal:
    fast = normalize_candles(candles.get(config.scan.intervals.fast, pd.DataFrame()))
    confirm = normalize_candles(candles.get(config.scan.intervals.confirm, pd.DataFrame()))
    htf = normalize_candles(candles.get(config.scan.intervals.htf, pd.DataFrame()))

    if fast.empty or confirm.empty or htf.empty:
        return _base_signal(
            light,
            grade="AVOID",
            model="Invalid/insufficient candle data",
            reasons=["캔들 데이터가 부족하거나 형식이 맞지 않아 분석에서 제외"],
            notes=["해당 실행에서는 건너뜀. 최종 판단은 사용자 몫."],
        )

    if config.portfolio.enabled and holding is not None:
        portfolio_signal = analyze_portfolio_holding(holding, light, candles, config)
        if portfolio_signal.grade in {"TAKE_PROFIT", "CUT_REDUCE"}:
            return portfolio_signal

    manual = config.manual_risk_symbols.get(light.symbol.upper())
    htf_bias = calculate_htf_bias(htf)
    location = premium_discount(htf, light.current_price)
    bullish_sweep, sweep_level = _bullish_sweep_any(light, fast, confirm)
    bearish_sweep, bearish_level = _bearish_sweep_any(light, fast, confirm)
    key_level = sweep_level or recent_swing_low(confirm) or light.low_24h
    body_recovery = has_body_recovery(confirm, key_level)
    bullish_mss, mss_level = detect_bullish_mss(fast)
    bullish_displacement = detect_bullish_displacement(fast, key_level=key_level)
    bearish_displacement = detect_bearish_displacement(confirm, key_level=bearish_level)
    expanding_volume = volume_is_expanding(fast)
    bullish_poi = _has_bullish_poi_near_price(confirm, light.current_price)

    target_1, target_2 = _targets(light, candles)
    invalidation = _invalidation(light, fast, confirm, key_level)
    rr = reward_risk(light.current_price, invalidation, target_1)
    risk_pct = max(0.0, (light.current_price - invalidation) / light.current_price * 100)
    sufficient_liquidity = (
        light.trade_value_24h >= config.liquidity.min_trade_value_krw_for_buy_signal
    )
    watch_liquidity = light.trade_value_24h >= config.liquidity.min_trade_value_krw_for_watch
    high_chase = light.range_position > 0.85
    strong_high_chase = high_chase and light.change_rate_24h >= 10
    event_risk = manual is not None and not manual.allow_buy_signal
    btc = btc_context or BtcContext()

    score = 0.0
    reasons: list[str] = []
    notes: list[str] = []

    if bullish_sweep:
        score += 20
        reasons.append("24H 저점 또는 최근 swing low 스윕 후 회복 시도")
    if body_recovery:
        score += 15
        reasons.append("15m 기준 key level 위 몸통 마감")
    if bullish_mss:
        score += 15
        reasons.append("5m bullish MSS 발생")
    if bullish_displacement:
        score += 10
        reasons.append("5m bullish displacement 발생")
    if expanding_volume:
        score += 5
        reasons.append("최근 평균 대비 거래량 증가")
    if location == "discount":
        score += 10
        reasons.append("1h range 기준 discount 위치")
    if rr >= config.risk.min_reward_risk:
        score += 10
        reasons.append(f"목표 DOL까지 RR {rr:.2f}")
    else:
        score -= 20
        reasons.append(f"RR {rr:.2f}로 기준 {config.risk.min_reward_risk:.2f} 미달")
    if sufficient_liquidity:
        score += 10
        reasons.append("24H 거래대금 기준 충족")
    else:
        score -= 20
        reasons.append("24H 거래대금이 BUY_NOW 기준 미달")
    if btc.stable:
        score += 10
        reasons.append("BTC 1h context 급락/저항 위험 낮음")
    else:
        score -= 10
        reasons.append("BTC 1h context가 알트 BUY에 불리함")

    if high_chase:
        score -= 20
        reasons.append("24H range 상단권으로 추격 진입 위험")
    if strong_high_chase:
        score -= 20
        reasons.append("24H 급등 후 상단권 과열")
    if light.change_rate_24h <= -20 and not body_recovery:
        score -= 15
        reasons.append("24H 큰 약세 후 몸통 회복 부족")
    if event_risk:
        score -= 30
        reasons.append(f"manual risk: {manual.reason}")
        notes.append("설정상 BUY_NOW 알림 차단")
    elif manual is not None and manual.reason:
        notes.append(f"manual note: {manual.reason}")

    htf_mid_bearish = htf_bias == "bearish" and 0.35 <= light.range_position <= 0.75
    strict_buy = (
        bullish_sweep
        and body_recovery
        and (bullish_mss or bullish_displacement)
        and rr >= config.risk.min_reward_risk
        and sufficient_liquidity
        and not event_risk
        and not high_chase
        and not htf_mid_bearish
        and btc.stable
    )

    if bearish_sweep or bearish_displacement:
        reasons.append("상단 유동성 스윕 또는 bearish displacement 감지")
        if high_chase:
            return _finalize_signal(
                light,
                "CONFIRM",
                score,
                "High-zone rejection watch",
                key_level=bearish_level,
                target_1=target_1,
                target_2=target_2,
                invalidation=invalidation,
                rr=rr,
                reasons=reasons,
                strategy=[
                    "상단 추격 금지",
                    "15m 몸통 회복 또는 breakout retest 확인 전까지 관망",
                ],
                notes=notes,
                candle_timestamp=latest_timestamp(confirm),
            )

    if strict_buy:
        grade: Grade
        if score >= 75:
            grade = "BUY_NOW_A"
        elif score >= 60:
            grade = "BUY_NOW_B"
        else:
            grade = "BUY_NOW_C"
        return _finalize_signal(
            light,
            grade,
            score,
            "Sweep Reversal Buy",
            key_level=key_level,
            target_1=target_1,
            target_2=target_2,
            invalidation=invalidation,
            rr=rr,
            reasons=reasons,
            strategy=_buy_strategy(light, invalidation, target_1, target_2, key_level),
            notes=notes + ["소액만. 최종 판단은 사용자 몫."],
            candle_timestamp=latest_timestamp(confirm),
            mss_level=mss_level,
        )

    if (
        not event_risk
        and not high_chase
        and watch_liquidity
        and risk_pct <= config.risk.max_entry_risk_pct * 1.8
        and rr >= config.risk.min_reward_risk * 0.8
        and (bullish_sweep or location == "discount" or bullish_poi or light.range_position <= 0.35)
    ):
        model = "Discount POI Buy" if bullish_poi or location == "discount" else "Retest/BID setup"
        return _finalize_signal(
            light,
            "BID",
            score,
            model,
            key_level=key_level,
            target_1=target_1,
            target_2=target_2,
            invalidation=invalidation,
            rr=rr,
            reasons=reasons or ["현재가는 즉시 진입보다 BID 대기 쪽이 보수적"],
            strategy=_bid_strategy(light, invalidation, target_1, target_2, key_level),
            notes=notes + ["최종 판단은 사용자 몫."],
            candle_timestamp=latest_timestamp(confirm),
        )

    if event_risk or not watch_liquidity or strong_high_chase:
        grade = "AVOID"
        model = "Risk filter"
    else:
        grade = "CONFIRM"
        model = "Recovery/retest needed"

    strategy = [
        "진입 가능 구간은 15m 몸통 회복과 retest 확인 후 재계산",
        f"무효화 기준: {format_krw(invalidation)} 아래 15m 몸통 마감",
    ]
    if htf_mid_bearish:
        strategy.insert(0, "1h bearish + 중간지대라 현물 BUY_NOW 제외")
    if rr < config.risk.min_reward_risk:
        strategy.insert(0, "목표 대비 손익비가 낮아 BUY_NOW 제외")

    return _finalize_signal(
        light,
        grade,
        score,
        model,
        key_level=key_level,
        target_1=target_1,
        target_2=target_2,
        invalidation=invalidation,
        rr=rr,
        reasons=reasons,
        strategy=strategy,
        notes=notes + ["최종 판단은 사용자 몫."],
        candle_timestamp=latest_timestamp(confirm),
    )


def analyze_portfolio_holding(
    holding: PortfolioHolding,
    light: LightScanResult,
    candles: dict[str, pd.DataFrame],
    config: AppConfig,
) -> Signal:
    htf = normalize_candles(candles.get(config.scan.intervals.htf, pd.DataFrame()))
    confirm = normalize_candles(candles.get(config.scan.intervals.confirm, pd.DataFrame()))
    pnl_pct = (light.current_price - holding.avg_price) / holding.avg_price * 100
    htf_bias = calculate_htf_bias(htf)
    support = recent_swing_low(confirm) or light.low_24h
    resistance = recent_swing_high(confirm) or light.high_24h

    if pnl_pct > 0 and light.range_position >= 0.82:
        return _finalize_signal(
            light,
            "TAKE_PROFIT",
            0,
            "Portfolio take profit",
            key_level=resistance,
            target_1=resistance,
            target_2=light.high_24h,
            invalidation=max(support, light.current_price * 0.97),
            rr=0,
            reasons=[
                f"평단 {format_krw(holding.avg_price)} 대비 수익권",
                "24H high 또는 최근 swing high 근처",
            ],
            strategy=[
                "30~50% 부분익절 후보",
                f"보호선: {format_krw(max(support, light.current_price * 0.97))}",
                "나머지는 breakout retest 성공 시 보유 후보",
            ],
            notes=["포트폴리오 기능을 켠 경우에만 생성됨. 최종 판단은 사용자 몫."],
            candle_timestamp=latest_timestamp(confirm),
            is_portfolio=True,
        )

    if pnl_pct < 0 and (htf_bias == "bearish" or light.current_price < support):
        recovery = min(holding.avg_price, light.current_price * 1.03)
        return _finalize_signal(
            light,
            "CUT_REDUCE",
            0,
            "Portfolio cut/reduce",
            key_level=support,
            target_1=recovery,
            target_2=holding.avg_price,
            invalidation=support,
            rr=0,
            reasons=[
                f"평단 {format_krw(holding.avg_price)} 대비 손실권",
                "1h bias bearish 또는 주요 지지선 이탈 위험",
            ],
            strategy=[
                "물타기 금지",
                f"{format_krw(recovery)} 회복 시 손실 축소 검토",
                f"{format_krw(holding.avg_price)} 접근 시 비중 축소/정리 후보",
                f"{format_krw(support)} 이탈 시 위험",
            ],
            notes=["포트폴리오 기능을 켠 경우에만 생성됨. 최종 판단은 사용자 몫."],
            candle_timestamp=latest_timestamp(confirm),
            is_portfolio=True,
        )

    return _finalize_signal(
        light,
        "HOLD",
        0,
        "Portfolio hold",
        key_level=support,
        target_1=resistance,
        target_2=light.high_24h,
        invalidation=support,
        rr=0,
        reasons=[f"평단 대비 수익률 {pnl_pct:.2f}%"],
        strategy=["추가 판단 신호 없음"],
        notes=["포트폴리오 기능을 켠 경우에만 생성됨. 최종 판단은 사용자 몫."],
        candle_timestamp=latest_timestamp(confirm),
        is_portfolio=True,
    )


def _bullish_sweep_any(
    light: LightScanResult,
    fast: pd.DataFrame,
    confirm: pd.DataFrame,
) -> tuple[bool, float | None]:
    for frame, level in ((confirm, light.low_24h), (fast, light.low_24h), (confirm, None), (fast, None)):
        swept, key = detect_bullish_sweep(frame, level)
        if swept:
            return True, key
    return False, None


def _bearish_sweep_any(
    light: LightScanResult,
    fast: pd.DataFrame,
    confirm: pd.DataFrame,
) -> tuple[bool, float | None]:
    for frame, level in (
        (confirm, light.high_24h),
        (fast, light.high_24h),
        (confirm, None),
        (fast, None),
    ):
        swept, key = detect_bearish_sweep(frame, level)
        if swept:
            return True, key
    return False, None


def _has_bullish_poi_near_price(df: pd.DataFrame, current_price: float) -> bool:
    for fvg in detect_fvgs(df):
        if fvg.get("type") != "bullish":
            continue
        low = float(fvg["low"])
        high = float(fvg["high"])
        if low * 0.995 <= current_price <= high * 1.02:
            return True
    return False


def _targets(light: LightScanResult, candles: dict[str, pd.DataFrame]) -> tuple[float, float]:
    levels = _dol_levels(light, candles)
    above = sorted(level for level in levels if level > light.current_price * 1.002)
    if not above:
        return light.current_price * 1.03, light.current_price * 1.06
    if len(above) == 1:
        return above[0], max(above[0] * 1.03, light.current_price * 1.06)
    return above[0], above[1]


def _dol_levels(light: LightScanResult, candles: dict[str, pd.DataFrame]) -> list[float]:
    levels = [light.high_24h, light.low_24h]
    for frame in candles.values():
        normalized = normalize_candles(frame)
        swing_high = recent_swing_high(normalized)
        swing_low = recent_swing_low(normalized)
        if swing_high is not None:
            levels.append(swing_high)
        if swing_low is not None:
            levels.append(swing_low)
    levels.extend(_round_levels(light.current_price))
    return sorted({round(level, 8) for level in levels if level > 0})


def _round_levels(price: float) -> list[float]:
    if price <= 0:
        return []
    magnitude = 10 ** math.floor(math.log10(price))
    step = magnitude / 2
    if price < 100:
        step = max(0.1, step)
    start = math.floor(price / step) - 4
    return [max(step, (start + offset) * step) for offset in range(10)]


def _invalidation(
    light: LightScanResult,
    fast: pd.DataFrame,
    confirm: pd.DataFrame,
    key_level: float,
) -> float:
    supports = [
        key_level * 0.995,
        light.low_24h * 0.995,
        light.current_price * 0.97,
    ]
    fast_low = recent_swing_low(fast, exclude_last=False)
    confirm_low = recent_swing_low(confirm, exclude_last=False)
    if fast_low is not None:
        supports.append(fast_low * 0.995)
    if confirm_low is not None:
        supports.append(confirm_low * 0.995)

    below_current = [support for support in supports if 0 < support < light.current_price]
    if not below_current:
        return light.current_price * 0.97
    return max(below_current)


def _buy_strategy(
    light: LightScanResult,
    invalidation: float,
    target_1: float,
    target_2: float,
    key_level: float,
) -> list[str]:
    entry_low = min(key_level, light.current_price) * 0.995
    entry_high = light.current_price * 1.003
    bid_low = invalidation * 1.002
    bid_high = key_level * 1.002
    return [
        f"공격형 진입: {format_krw(entry_low)}~{format_krw(entry_high)}",
        f"BID: {format_krw(bid_low)}~{format_krw(bid_high)}",
        f"1차 목표: {format_krw(target_1)}",
        f"2차 목표: {format_krw(target_2)}",
        f"무효화: {format_krw(invalidation)} 아래 15분봉 몸통 마감",
        "손절 기준: 무효화 이탈 시 시나리오 폐기",
    ]


def _bid_strategy(
    light: LightScanResult,
    invalidation: float,
    target_1: float,
    target_2: float,
    key_level: float,
) -> list[str]:
    bid_low = invalidation * 1.002
    bid_high = min(light.current_price * 0.995, key_level * 1.005)
    if bid_high <= bid_low:
        bid_high = light.current_price * 0.995
    return [
        f"진입 가능 구간: {format_krw(bid_low)}~{format_krw(bid_high)}",
        f"BID 가격: {format_krw(bid_low)}~{format_krw(bid_high)}",
        f"1차 목표: {format_krw(target_1)}",
        f"2차 목표: {format_krw(target_2)}",
        f"무효화: {format_krw(invalidation)} 아래 15분봉 몸통 마감",
        "손절 기준: 무효화 이탈 시 대기 주문 관점 폐기",
    ]


def _base_signal(
    light: LightScanResult,
    grade: Grade,
    model: str,
    reasons: list[str],
    notes: list[str],
) -> Signal:
    return Signal(
        symbol=light.symbol,
        grade=grade,
        model=model,
        current_price=light.current_price,
        low_24h=light.low_24h,
        high_24h=light.high_24h,
        range_position=light.range_position,
        key_level=light.current_price,
        candle_timestamp="",
        reasons=reasons,
        notes=notes,
    )


def _finalize_signal(
    light: LightScanResult,
    grade: Grade,
    score: float,
    model: str,
    key_level: float | None,
    target_1: float,
    target_2: float,
    invalidation: float,
    rr: float,
    reasons: list[str],
    strategy: list[str],
    notes: list[str],
    candle_timestamp: str,
    mss_level: float | None = None,
    is_portfolio: bool = False,
) -> Signal:
    bid_low = invalidation * 1.002 if invalidation else None
    bid_high = min(light.current_price * 0.995, (key_level or light.current_price) * 1.005)
    if bid_low is not None and bid_high <= bid_low:
        bid_high = light.current_price * 0.995

    if mss_level is not None and key_level is None:
        key_level = mss_level

    return Signal(
        symbol=light.symbol,
        grade=grade,
        score=round(score, 2),
        model=model,
        current_price=light.current_price,
        low_24h=light.low_24h,
        high_24h=light.high_24h,
        range_position=light.range_position,
        entry_price=light.current_price,
        bid_low=bid_low,
        bid_high=bid_high,
        target_1=target_1,
        target_2=target_2,
        invalidation=invalidation,
        reward_risk=round(rr, 2),
        key_level=key_level,
        candle_timestamp=candle_timestamp,
        reasons=reasons,
        strategy=strategy,
        notes=notes,
        is_portfolio=is_portfolio,
    )

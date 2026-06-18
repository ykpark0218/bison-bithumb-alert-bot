from __future__ import annotations

import os

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from bison_bot.models import Signal
from bison_bot.utils import chunk_text, format_krw, get_logger


class TelegramClient:
    def __init__(
        self,
        token: str | None = None,
        chat_id: str | None = None,
        dry_run: bool = False,
    ) -> None:
        self.token = token if token is not None else os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id if chat_id is not None else os.getenv("TELEGRAM_CHAT_ID", "")
        self.dry_run = dry_run or not self.token or not self.chat_id
        self.logger = get_logger("telegram")

    @property
    def delivers(self) -> bool:
        return not self.dry_run and bool(self.token and self.chat_id)

    def send_message(self, text: str) -> bool:
        for chunk in chunk_text(text):
            if self.dry_run:
                print("\n--- DRY RUN TELEGRAM MESSAGE ---")
                print(chunk)
                continue
            self._post_message(chunk)
        return self.delivers

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _post_message(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        response = requests.post(
            url,
            data={
                "chat_id": self.chat_id,
                "text": text,
                "disable_web_page_preview": "true",
            },
            timeout=10,
        )
        response.raise_for_status()


def format_signal_message(signal: Signal) -> str:
    header = f"{signal.grade} | {signal.symbol}/KRW"
    if signal.is_portfolio:
        header = f"PORTFOLIO {header}"

    lines = [
        header,
        f"현재가: {format_krw(signal.current_price)}",
    ]
    if signal.low_24h is not None and signal.high_24h is not None:
        lines.append(f"24H: 저점 {format_krw(signal.low_24h)} / 고점 {format_krw(signal.high_24h)}")
    if signal.range_position is not None:
        lines.append(f"Range position: {signal.range_position:.2f}")
    if signal.score:
        lines.append(f"Score: {signal.score:.1f}")
    if signal.reward_risk:
        lines.append(f"RR: {signal.reward_risk:.2f}")
    lines.append(f"모델: {signal.model}")

    if signal.reasons:
        lines.append("")
        lines.append("근거:")
        lines.extend(f"- {reason}" for reason in signal.reasons)

    if signal.strategy:
        lines.append("")
        lines.append("전략:")
        lines.extend(f"- {item}" for item in signal.strategy)

    if signal.notes:
        lines.append("")
        lines.append("비고:")
        lines.extend(signal.notes)
    elif "최종 판단은 사용자 몫" not in "\n".join(lines):
        lines.append("")
        lines.append("비고:")
        lines.append("최종 판단은 사용자 몫.")

    return "\n".join(lines)


def format_summary_message(
    total_symbols: int,
    deep_symbols: int,
    grade_counts: dict[str, int],
    summary_signals: list[Signal],
) -> str:
    lines = [
        "BITHUMB KRW FULL SCAN SUMMARY",
        f"전체 light scan 종목 수: {total_symbols}",
        f"deep scan 종목 수: {deep_symbols}",
        "",
        "등급별 개수:",
    ]
    for grade, count in sorted(grade_counts.items()):
        lines.append(f"- {grade}: {count}")

    if summary_signals:
        lines.append("")
        lines.append("요약 후보:")
        for signal in summary_signals[:20]:
            range_text = "-" if signal.range_position is None else f"{signal.range_position:.2f}"
            lines.append(
                f"- {signal.grade} {signal.symbol}: {signal.model}, "
                f"range {range_text}"
            )

    lines.append("")
    lines.append("알림은 차트 기반 참고 도구입니다. 최종 판단은 사용자 몫.")
    return "\n".join(lines)

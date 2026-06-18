from __future__ import annotations

from typing import Any

import requests

from bison_bot.telegram import TelegramClient


class FakeResponse:
    def raise_for_status(self) -> None:
        return None


def test_telegram_dry_run_does_not_post(monkeypatch) -> None:
    called = False

    def fake_post(*args: Any, **kwargs: Any) -> FakeResponse:
        nonlocal called
        called = True
        return FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)

    client = TelegramClient(token="token", chat_id="chat", dry_run=True)
    delivered = client.send_message("hello")

    assert delivered is False
    assert called is False


def test_telegram_post_uses_timeout(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    def fake_post(url: str, data: dict[str, str], timeout: float) -> FakeResponse:
        seen["url"] = url
        seen["data"] = data
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)

    client = TelegramClient(token="token", chat_id="chat", dry_run=False)
    delivered = client.send_message("hello")

    assert delivered is True
    assert seen["timeout"] == 10
    assert seen["url"] == "https://api.telegram.org/bottoken/sendMessage"
    assert seen["data"]["chat_id"] == "chat"
    assert seen["data"]["text"] == "hello"

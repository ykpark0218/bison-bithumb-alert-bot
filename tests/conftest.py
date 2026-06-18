from __future__ import annotations

import faulthandler
from typing import Any

import pytest
import requests

_ORIGINAL_REQUEST = requests.sessions.Session.request


def _blocked_request(self: requests.Session, method: str, url: str, **kwargs: Any) -> Any:
    raise RuntimeError(
        f"Network access is disabled during tests: {method.upper()} {url}. "
        "Use monkeypatch or a fake client instead."
    )


def pytest_configure(config: pytest.Config) -> None:
    requests.sessions.Session.request = _blocked_request
    faulthandler.dump_traceback_later(30, exit=True)


@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    faulthandler.cancel_dump_traceback_later()


def pytest_unconfigure(config: pytest.Config) -> None:
    requests.sessions.Session.request = _ORIGINAL_REQUEST
    faulthandler.cancel_dump_traceback_later()

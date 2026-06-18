from __future__ import annotations

import pandas as pd

from bison_bot.rules import range_position, remove_open_candle


def test_range_position_calculation() -> None:
    assert range_position(15, 10, 20) == 0.5
    assert range_position(5, 10, 20) == 0.0
    assert range_position(25, 10, 20) == 1.0
    assert range_position(10, 10, 10) == 0.5


def test_remove_open_candle() -> None:
    frame = pd.DataFrame(
        [
            {
                "timestamp": "2026-06-18 10:00:00",
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "volume": 10,
            },
            {
                "timestamp": "2026-06-18 10:05:00",
                "open": 100,
                "high": 102,
                "low": 99,
                "close": 101,
                "volume": 20,
            },
        ]
    )

    closed = remove_open_candle(frame, "5m", now="2026-06-18 10:07:00")

    assert len(closed) == 1
    assert str(closed.iloc[-1]["timestamp"]) == "2026-06-18 10:00:00"

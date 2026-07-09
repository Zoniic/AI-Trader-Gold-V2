"""สัญญาข้อมูล (contract) ระหว่างกลยุทธ์ กับ backtest engine / execution ในอนาคต

ทุกกลยุทธ์ต้องคืน Signal เท่านั้น ห้ามเปลี่ยนรูปแบบ field พวกนี้ —
ถ้าต่อ execution layer ในอนาคต จะอ่านแค่ direction/entry/sl/tp เหมือนที่ backtest ใช้
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pandas as pd


class Direction(Enum):
    BUY = "BUY"
    SELL = "SELL"
    FLAT = "FLAT"

    @property
    def sign(self) -> int:
        return {"BUY": 1, "SELL": -1, "FLAT": 0}[self.value]


@dataclass
class Signal:
    direction: Direction
    entry: float | None = None
    sl: float | None = None
    tp: float | None = None
    reason: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def is_actionable(self) -> bool:
        return self.direction != Direction.FLAT and self.sl is not None and self.tp is not None

    @classmethod
    def flat(cls, reason: str = "no setup") -> "Signal":
        return cls(direction=Direction.FLAT, reason=reason)


@dataclass
class MarketData:
    """ครอบ DataFrame แท่งเทียน single-timeframe เดียว (เพิ่ม multi-timeframe ทีหลังถ้าจำเป็นจริง)

    คอลัมน์ที่ต้องมี: open, high, low, close, volume — index เป็นเวลา (DatetimeIndex)
    """

    df: pd.DataFrame
    symbol: str = "XAUUSD"

    def __len__(self) -> int:
        return len(self.df)

    def window(self, end_idx: int, lookback: int) -> pd.DataFrame:
        """คืนข้อมูลย้อนหลังถึง idx=end_idx (รวม) เท่านั้น กัน lookahead bias"""
        start_idx = max(0, end_idx - lookback + 1)
        return self.df.iloc[start_idx : end_idx + 1]

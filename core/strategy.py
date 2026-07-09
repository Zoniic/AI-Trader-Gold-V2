"""Strategy base class + registry สำหรับเสียบกลยุทธ์ใหม่แบบไม่ต้องแก้โค้ดที่อื่น"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.signal import Direction, MarketData, Signal

STRATEGY_REGISTRY: dict[str, type["Strategy"]] = {}


def register_strategy(cls: type["Strategy"]) -> type["Strategy"]:
    """Class decorator: แปะไว้บน Strategy subclass เพื่อลงทะเบียนอัตโนมัติ"""
    STRATEGY_REGISTRY[cls.name] = cls
    return cls


class Strategy:
    name: str = "base"
    description: str = ""  # อธิบายท่าเทรด (entry/exit) แบบสั้น ให้คนอ่านโค้ดไม่ออกก็เข้าใจได้

    def evaluate(self, data: MarketData, idx: int) -> Signal:
        """คำนวณสัญญาณที่แท่งเทียน idx โดยห้ามมองข้อมูลเกิน idx (กัน lookahead)"""
        raise NotImplementedError

    def params(self) -> dict:
        """คืนพารามิเตอร์จริงที่ instance นี้ใช้อยู่ (เฉพาะค่า primitive — กัน object ภายในหลุดไป JSON)"""
        return {
            k: v
            for k, v in vars(self).items()
            if not k.startswith("_") and isinstance(v, (int, float, str, bool))
        }

    def committee_info(self) -> list[dict]:
        """รายชื่อ+บทบาทนักเทรดในทีม (ถ้าทีมนี้มี committee) สำหรับแสดงบน dashboard"""
        committee = getattr(self, "_committee", None)
        if committee is None:
            return []
        return [{"name": m.name, "role": m.role} for m in committee.members]

    def build_ctx(
        self,
        window: pd.DataFrame,
        bar_time,
        direction: Direction,
        entry: float,
        sl: float,
        tp: float,
        atr: float,
        setup_comment: str,
        **extra,
    ) -> dict:
        """สร้าง context มาตรฐานให้คณะกรรมการดู — คำนวณ atr_median/adx จาก window เท่านั้น (กัน lookahead)"""
        from backtest.regime import compute_adx  # import ตรงนี้กัน circular import ตอนโหลดโมดูล

        tr = pd.concat(
            [
                window["high"] - window["low"],
                (window["high"] - window["close"].shift(1)).abs(),
                (window["low"] - window["close"].shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr_series = tr.rolling(14).mean().dropna()
        atr_median = float(atr_series.median()) if len(atr_series) else atr

        adx = float(compute_adx(window).iloc[-1])

        ctx = {
            "bar_time": bar_time,
            "direction": direction,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "atr": atr,
            "atr_median": atr_median,
            "adx": adx,
            "setup_comment": setup_comment,
        }
        ctx.update(extra)
        return ctx

    @staticmethod
    def atr(df: pd.DataFrame, period: int = 14) -> float:
        high, low, close = df["high"], df["low"], df["close"]
        prev_close = close.shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
        ).max(axis=1)
        return float(tr.rolling(period).mean().iloc[-1])

    @staticmethod
    def rsi(close: pd.Series, period: int = 14) -> pd.Series:
        """RSI แบบ Wilder — คืนทั้ง series (บางทีมต้องดูค่าย้อนหลัง เช่นหา divergence)"""
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return (100 - 100 / (1 + rs)).fillna(50.0)

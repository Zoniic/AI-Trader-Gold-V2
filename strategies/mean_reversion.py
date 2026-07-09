"""ทีม 2 "Rubber Band" — mean reversion ด้วย Bollinger Bands + RSI (แนว Linda Raschke)

นักเทรด 5 คน: มาดามมีนเสนอไม้เมื่อราคาหลุดกรอบ+RSI สุดโต่ง แล้วอีก 4 คน review
โดยเฉพาะกันเข้าไม้สวนตอนเทรนด์แรง (จุดตายของท่านี้) และตอนกรอบกำลังระเบิด (breakout)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.committee import (
    Committee,
    CommitteeMember,
    make_proposer,
    make_risk_officer,
    make_session_analyst,
    make_trend_analyst,
)
from core.signal import Direction, MarketData, Signal
from core.strategy import Strategy, register_strategy


def _make_bandwidth_analyst(name: str, max_expand_ratio: float = 1.8) -> CommitteeMember:
    """กันเข้าไม้ตอนกรอบ Bollinger กำลังระเบิดกว้างขึ้นเร็ว (สัญญาณ breakout ไม่ใช่ reversion)"""

    def check(ctx: dict) -> tuple[bool, str]:
        bw_now, bw_before = ctx["bandwidth_now"], ctx["bandwidth_before"]
        if bw_before <= 0:
            return False, "ความกว้างกรอบก่อนหน้าผิดปกติ ค้าน"
        ratio = bw_now / bw_before
        if ratio > max_expand_ratio:
            return False, (
                f"กรอบ Bollinger ขยาย {ratio:.1f} เท่าใน 10 แท่ง (> {max_expand_ratio:.1f}x) "
                "น่าจะเป็น breakout จริง ไม่ใช่จังหวะสวน ค้าน"
            )
        return True, f"กรอบขยาย {ratio:.1f} เท่า ยังอยู่ในโหมดแกว่งปกติ"

    return CommitteeMember(name, "Bandwidth Analyst", check)


@register_strategy
class MeanReversionStrategy(Strategy):
    name = "mean_reversion"
    description = (
        "Mean reversion แนว counter-trend (สไตล์ Linda Raschke): เข้า BUY เมื่อราคาหลุดกรอบ "
        "Bollinger ล่างพร้อม RSI <= rsi_oversold, SELL เมื่อหลุดกรอบบนพร้อม RSI >= rsi_overbought "
        "— TP อยู่ที่เส้นกลาง (SMA) เพราะคาดว่าราคาย้อนกลับสู่ค่าเฉลี่ย SL จาก ATR "
        "เหมาะกับตลาดแกว่งกรอบ คณะกรรมการช่วยกันไม้สวนตอนเทรนด์แรง/กรอบกำลังระเบิด"
    )

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        atr_period: int = 14,
        atr_mult_sl: float = 1.5,
        min_tp_atr_mult: float = 0.3,
    ):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.atr_period = atr_period
        self.atr_mult_sl = atr_mult_sl
        self.min_tp_atr_mult = min_tp_atr_mult
        self._committee = Committee(
            [
                make_proposer("มาดามมีน"),
                make_trend_analyst("โปรเงียบ", mode="need_quiet", adx_threshold=32.0),
                _make_bandwidth_analyst("อาจารย์แบนด์"),
                make_risk_officer("พี่กัน", min_rr=0.7),
                make_session_analyst("น้องนาฬิกา"),
            ]
        )

    def min_lookback(self) -> int:
        return max(self.bb_period, self.rsi_period, self.atr_period) + 20

    def _rsi(self, close: pd.Series) -> float:
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / self.rsi_period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / self.rsi_period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1]) if not np.isnan(rsi.iloc[-1]) else 50.0

    def evaluate(self, data: MarketData, idx: int) -> Signal:
        lookback = self.min_lookback()
        if idx < lookback:
            return Signal.flat("ข้อมูลไม่พอ (warmup)")

        window = data.window(idx, lookback)
        close = window["close"]

        sma = close.rolling(self.bb_period).mean()
        std = close.rolling(self.bb_period).std()
        upper_series = sma + self.bb_std * std
        lower_series = sma - self.bb_std * std
        upper = float(upper_series.iloc[-1])
        lower = float(lower_series.iloc[-1])
        mid = float(sma.iloc[-1])

        last_close = float(close.iloc[-1])
        rsi = self._rsi(close)

        atr = self.atr(window, self.atr_period)
        if atr <= 0:
            return Signal.flat("ATR ไม่ถูกต้อง")

        if last_close <= lower and rsi <= self.rsi_oversold:
            direction = Direction.BUY
        elif last_close >= upper and rsi >= self.rsi_overbought:
            direction = Direction.SELL
        else:
            return Signal.flat("ไม่เข้าเกณฑ์ oversold/overbought พร้อมกัน")

        tp = mid  # เป้าหมาย mean reversion คือกลับไปที่เส้นกลาง
        if abs(tp - last_close) < atr * self.min_tp_atr_mult:
            return Signal.flat("ระยะถึงเส้นกลางสั้นเกินไป ไม่คุ้มต้นทุน")

        sl = last_close - direction.sign * (atr * self.atr_mult_sl)

        bandwidth_now = float((upper_series - lower_series).iloc[-1])
        bandwidth_before = float((upper_series - lower_series).iloc[-11])

        ctx = self.build_ctx(
            window=window,
            bar_time=window.index[-1],
            direction=direction,
            entry=last_close,
            sl=sl,
            tp=tp,
            atr=atr,
            setup_comment=(
                f"ราคา {last_close:.2f} หลุดกรอบ{'ล่าง' if direction == Direction.BUY else 'บน'} "
                f"({lower:.2f}/{upper:.2f}) พร้อม RSI {rsi:.1f} เสนอสวน {direction.value} เป้าเส้นกลาง {mid:.2f}"
            ),
            bandwidth_now=bandwidth_now,
            bandwidth_before=bandwidth_before,
        )
        approved, opinions = self._committee.review(ctx)
        if not approved:
            vetoes = [o["member"] for o in opinions if not o["approve"]]
            return Signal.flat(f"คณะกรรมการไม่อนุมัติ ({', '.join(vetoes)} ค้าน)")

        return Signal(
            direction=direction,
            entry=last_close,
            sl=sl,
            tp=tp,
            reason=f"BB{self.bb_period}/{self.bb_std} + RSI({rsi:.1f}) "
            f"{'oversold' if direction == Direction.BUY else 'overbought'}",
            meta={"discussion": opinions},
        )

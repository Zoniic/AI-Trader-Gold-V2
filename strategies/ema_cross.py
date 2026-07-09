"""ทีม 1 "Golden Cross" — trend-following ด้วย EMA crossover (สำนัก momentum คลาสสิก)

นักเทรด 5 คน: กัปตันโกลด์เสนอไม้เมื่อ EMA ตัดกัน แล้วอีก 4 คน review คนละด้าน
(เทรนด์/ความผันผวน/ความเสี่ยง/ช่วงเวลา) ค้านได้ไม่เกิน 1 เสียงถึงเข้าไม้จริง
"""
from __future__ import annotations

from core.committee import (
    Committee,
    make_proposer,
    make_risk_officer,
    make_session_analyst,
    make_trend_analyst,
    make_volatility_analyst,
)
from core.signal import Direction, MarketData, Signal
from core.strategy import Strategy, register_strategy


@register_strategy
class EMACrossStrategy(Strategy):
    name = "ema_cross"
    description = (
        "Trend-following สำนัก momentum คลาสสิก: เข้า BUY เมื่อ EMA เร็ว (fast) ตัดขึ้นเหนือ "
        "EMA ช้า (slow), เข้า SELL เมื่อตัดลง — SL/TP คำนวณจาก ATR คูณ atr_mult_sl/atr_mult_tp "
        "เท่าจากราคาเข้า (R:R 1:2 คงที่) ออกแบบมาสำหรับตลาดที่มีเทรนด์ชัดเจนต่อเนื่อง "
        "คณะกรรมการ 5 คนช่วยกรองไม้ตอนเทรนด์อ่อน/ข่าวแรง/ช่วง rollover ออก"
    )

    def __init__(
        self,
        fast: int = 20,
        slow: int = 50,
        atr_period: int = 14,
        atr_mult_sl: float = 1.5,
        atr_mult_tp: float = 3.0,
    ):
        self.fast = fast
        self.slow = slow
        self.atr_period = atr_period
        self.atr_mult_sl = atr_mult_sl
        self.atr_mult_tp = atr_mult_tp
        self._committee = Committee(
            [
                make_proposer("กัปตันโกลด์"),
                make_trend_analyst("พี่หมี", mode="need_trend", adx_threshold=18.0),
                make_volatility_analyst("เจ๊วอล", max_spike_ratio=2.5),
                make_risk_officer("คุณเข้ม", min_rr=1.5),
                make_session_analyst("น้องไทม์"),
            ]
        )

    def min_lookback(self) -> int:
        return self.slow + self.atr_period + 5

    def evaluate(self, data: MarketData, idx: int) -> Signal:
        lookback = self.min_lookback()
        if idx < lookback:
            return Signal.flat("ข้อมูลไม่พอ (warmup)")

        window = data.window(idx, lookback)
        ema_fast = window["close"].ewm(span=self.fast, adjust=False).mean()
        ema_slow = window["close"].ewm(span=self.slow, adjust=False).mean()

        prev_diff = ema_fast.iloc[-2] - ema_slow.iloc[-2]
        curr_diff = ema_fast.iloc[-1] - ema_slow.iloc[-1]

        crossed_up = prev_diff <= 0 and curr_diff > 0
        crossed_down = prev_diff >= 0 and curr_diff < 0

        if not (crossed_up or crossed_down):
            return Signal.flat("ไม่มี crossover")

        atr = self.atr(window, self.atr_period)
        if atr <= 0:
            return Signal.flat("ATR ไม่ถูกต้อง")

        entry = float(window["close"].iloc[-1])
        direction = Direction.BUY if crossed_up else Direction.SELL
        sl = entry - direction.sign * (atr * self.atr_mult_sl)
        tp = entry + direction.sign * (atr * self.atr_mult_tp)

        ctx = self.build_ctx(
            window=window,
            bar_time=window.index[-1],
            direction=direction,
            entry=entry,
            sl=sl,
            tp=tp,
            atr=atr,
            setup_comment=(
                f"EMA{self.fast} ตัด{'ขึ้นเหนือ' if crossed_up else 'ลงใต้'} EMA{self.slow} "
                f"ที่ราคา {entry:.2f} เสนอ {direction.value}"
            ),
        )
        approved, opinions = self._committee.review(ctx)
        if not approved:
            vetoes = [o["member"] for o in opinions if not o["approve"]]
            return Signal.flat(f"คณะกรรมการไม่อนุมัติ ({', '.join(vetoes)} ค้าน)")

        return Signal(
            direction=direction,
            entry=entry,
            sl=sl,
            tp=tp,
            reason=f"EMA{self.fast}/{self.slow} crossover {'up' if crossed_up else 'down'}",
            meta={"discussion": opinions},
        )

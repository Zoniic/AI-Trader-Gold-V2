"""ทีม 9 "Range Expanders" — volatility breakout (แนว Larry Williams)

หลักการจากหนังสือของ Larry Williams: วันที่ราคาวิ่งจากราคาเปิดเกินสัดส่วน k ของ
ช่วงราคาวันก่อนหน้า (range expansion) มักเป็นวันเทรนด์ วิ่งต่อทางเดิมจนปิดตลาด
เข้าตามทิศที่ราคาทะลุ threshold = open วันนี้ ± k×(range เมื่อวาน)
"""
from __future__ import annotations

import numpy as np

from core.committee import (
    Committee,
    CommitteeMember,
    make_proposer,
    make_risk_officer,
    make_session_analyst,
)
from core.signal import Direction, MarketData, Signal
from core.strategy import Strategy, register_strategy


def _make_gap_analyst(name: str, max_gap_atr: float = 1.0) -> CommitteeMember:
    """วันเปิดกระโดด (gap) ไกลจากปิดเมื่อวาน = threshold ของสูตรเพี้ยน ไม่ควรใช้"""

    def check(ctx: dict) -> tuple[bool, str]:
        gap_atr = ctx["day_gap"] / ctx["atr"] if ctx["atr"] > 0 else 99
        if gap_atr > max_gap_atr:
            return False, f"วันนี้เปิด gap {gap_atr:.1f} ATR จากปิดเมื่อวาน สูตร expansion เพี้ยน ค้าน"
        return True, f"เปิดห่างปิดเมื่อวานแค่ {gap_atr:.1f} ATR สูตรใช้ได้ปกติ"

    return CommitteeMember(name, "Gap Analyst", check)


def _make_range_power_analyst(name: str, min_atr_mult: float = 1.0) -> CommitteeMember:
    """range เมื่อวานต้องใหญ่พอ — วันก่อนหน้านิ่งสนิท threshold จะแคบจนหลุดมั่ว"""

    def check(ctx: dict) -> tuple[bool, str]:
        power = ctx["prev_range"] / ctx["atr"] if ctx["atr"] > 0 else 0
        if power < min_atr_mult:
            return False, f"range เมื่อวานแค่ {power:.1f} ATR (<{min_atr_mult}) threshold แคบเกิน ค้าน"
        return True, f"range เมื่อวาน {power:.1f} ATR ใหญ่พอให้ threshold มีความหมาย"

    return CommitteeMember(name, "Range Power Analyst", check)


@register_strategy
class VolatilityBreakoutStrategy(Strategy):
    name = "volatility_breakout"
    description = (
        "Volatility breakout แนว Larry Williams: threshold = ราคาเปิดวันนี้ ± k×(ช่วงราคาเมื่อวาน) "
        "— ถ้าราคาวิ่งทะลุ threshold แปลว่าวันนี้เป็นวัน range expansion มักวิ่งต่อทางเดิม "
        "เข้าตามทิศนั้น SL 1.2×ATR TP 2.4×ATR ปฏิเสธวันที่เปิด gap ไกล (สูตรเพี้ยน) "
        "และวันที่เมื่อวานนิ่งเกิน (threshold แคบจนหลอก)"
    )

    def __init__(
        self,
        k: float = 0.6,
        atr_period: int = 14,
        atr_mult_sl: float = 1.2,
        atr_mult_tp: float = 2.4,
        min_prev_day_bars: int = 12,
    ):
        self.k = k
        self.atr_period = atr_period
        self.atr_mult_sl = atr_mult_sl
        self.atr_mult_tp = atr_mult_tp
        self.min_prev_day_bars = min_prev_day_bars
        self._committee = Committee(
            [
                make_proposer("แลร์รี่สอง"),
                _make_gap_analyst("เจ๊แก๊ป"),
                _make_range_power_analyst("ตาวัด"),
                make_risk_officer("ปลัดเสี่ยง", min_rr=1.5),
                make_session_analyst("ยายโมง"),
            ]
        )

    def min_lookback(self) -> int:
        return 80  # ครอบคลุมวันนี้ + เมื่อวานเต็มวัน + ATR warmup

    def evaluate(self, data: MarketData, idx: int) -> Signal:
        lookback = self.min_lookback()
        if idx < lookback:
            return Signal.flat("ข้อมูลไม่พอ (warmup)")

        window = data.window(idx, lookback)
        bar_time = window.index[-1]
        dates = np.array([t.date() for t in window.index])
        today = bar_time.date()

        today_bars = window[dates == today]
        if len(today_bars) < 2:
            return Signal.flat("วันนี้ยังมีข้อมูลไม่พอ")

        prev_dates = sorted({d for d in dates if d < today})
        if not prev_dates:
            return Signal.flat("ไม่มีข้อมูลวันก่อนหน้าใน window")
        prev_day_bars = window[dates == prev_dates[-1]]
        if len(prev_day_bars) < self.min_prev_day_bars:
            return Signal.flat("ข้อมูลวันก่อนหน้าไม่ครบพอ")

        day_open = float(today_bars["open"].iloc[0])
        prev_range = float(prev_day_bars["high"].max() - prev_day_bars["low"].min())
        prev_day_close = float(prev_day_bars["close"].iloc[-1])
        day_gap = abs(day_open - prev_day_close)

        threshold_up = day_open + self.k * prev_range
        threshold_down = day_open - self.k * prev_range

        prev_close = float(window["close"].iloc[-2])
        last_close = float(window["close"].iloc[-1])

        atr = self.atr(window, self.atr_period)
        if atr <= 0 or prev_range <= 0:
            return Signal.flat("ATR/range ไม่ถูกต้อง")

        if prev_close <= threshold_up < last_close:
            direction = Direction.BUY
            broken = threshold_up
        elif prev_close >= threshold_down > last_close:
            direction = Direction.SELL
            broken = threshold_down
        else:
            return Signal.flat("ราคายังไม่ทะลุ threshold expansion")

        entry = last_close
        sl = entry - direction.sign * (atr * self.atr_mult_sl)
        tp = entry + direction.sign * (atr * self.atr_mult_tp)

        ctx = self.build_ctx(
            window=window,
            bar_time=bar_time,
            direction=direction,
            entry=entry,
            sl=sl,
            tp=tp,
            atr=atr,
            setup_comment=(
                f"ราคาทะลุ threshold {broken:.2f} (เปิดวันนี้ {day_open:.2f} "
                f"{'+' if direction == Direction.BUY else '-'} {self.k}×range เมื่อวาน {prev_range:.2f}) "
                f"วันนี้เป็นวัน expansion เสนอ {direction.value}"
            ),
            day_gap=day_gap,
            prev_range=prev_range,
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
            reason=f"Volatility breakout k={self.k} {'up' if direction == Direction.BUY else 'down'}",
            meta={"discussion": opinions},
        )

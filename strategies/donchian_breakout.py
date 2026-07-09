"""ทีม 3 "Turtle Squad" — Donchian channel breakout (แนว Turtle Traders ของ Richard Dennis)

หลักการดั้งเดิมของเต่า: ซื้อเมื่อราคาทะลุจุดสูงสุด N แท่ง ขายเมื่อทะลุจุดต่ำสุด N แท่ง
SL กว้าง 2×ATR ตามสูตรเต่า (ยอมโดน SL น้อยครั้งแต่ให้ไม้ที่ถูกวิ่งไกล) เป้า 4×ATR
"""
from __future__ import annotations

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


def _make_expansion_analyst(
    name: str, min_ratio: float = 0.8, max_ratio: float = 3.0
) -> CommitteeMember:
    """Breakout ที่ดีต้องมีพลัง (ATR ไม่แฟบ) แต่ไม่ใช่ตลาดคลั่ง (ATR ไม่พุ่งเกิน)"""

    def check(ctx: dict) -> tuple[bool, str]:
        ratio = ctx["atr"] / ctx["atr_median"] if ctx["atr_median"] > 0 else 0
        if ratio < min_ratio:
            return False, f"ATR แค่ {ratio:.2f} เท่าของปกติ (<{min_ratio}) breakout ไร้พลัง น่าจะหลอก ค้าน"
        if ratio > max_ratio:
            return False, f"ATR พุ่ง {ratio:.1f} เท่า (>{max_ratio}) ตลาดคลั่ง สลิปเพจจะกินหมด ค้าน"
        return True, f"ATR {ratio:.2f} เท่าของปกติ — breakout มีพลังกำลังดี"

    return CommitteeMember(name, "Expansion Analyst", check)


@register_strategy
class DonchianBreakoutStrategy(Strategy):
    name = "donchian_breakout"
    description = (
        "Channel breakout แนว Turtle Traders (Richard Dennis): เข้า BUY เมื่อราคาปิดทะลุ "
        "จุดสูงสุด dc_period แท่งก่อนหน้า, SELL เมื่อทะลุจุดต่ำสุด — SL กว้าง 2×ATR ตาม "
        "สูตรเต่าดั้งเดิม TP 4×ATR (R:R 1:2) ปรัชญา: แพ้บ่อยครั้งเล็ก ชนะน้อยครั้งแต่ใหญ่ "
        "เหมาะกับตลาดที่เกิดเทรนด์ใหม่แรงๆ"
    )

    def __init__(
        self,
        dc_period: int = 20,
        atr_period: int = 14,
        atr_mult_sl: float = 2.0,
        atr_mult_tp: float = 4.0,
    ):
        self.dc_period = dc_period
        self.atr_period = atr_period
        self.atr_mult_sl = atr_mult_sl
        self.atr_mult_tp = atr_mult_tp
        self._committee = Committee(
            [
                make_proposer("เต่าหัวหน้า"),
                make_trend_analyst("เต่าเทรนด์", mode="need_trend", adx_threshold=20.0),
                _make_expansion_analyst("เต่าพลัง"),
                make_risk_officer("เต่ากันภัย", min_rr=1.5),
                make_session_analyst("เต่าเวลา"),
            ]
        )

    def min_lookback(self) -> int:
        return self.dc_period + self.atr_period + 20

    def evaluate(self, data: MarketData, idx: int) -> Signal:
        lookback = self.min_lookback()
        if idx < lookback:
            return Signal.flat("ข้อมูลไม่พอ (warmup)")

        window = data.window(idx, lookback)
        # ช่องแชนแนลจาก dc_period แท่ง "ก่อนหน้า" (ไม่รวมแท่งปัจจุบัน — กันนับตัวเองเป็น breakout)
        channel_high = float(window["high"].iloc[-(self.dc_period + 1) : -1].max())
        channel_low = float(window["low"].iloc[-(self.dc_period + 1) : -1].min())

        prev_close = float(window["close"].iloc[-2])
        last_close = float(window["close"].iloc[-1])

        if prev_close <= channel_high < last_close:
            direction = Direction.BUY
            broken_level = channel_high
        elif prev_close >= channel_low > last_close:
            direction = Direction.SELL
            broken_level = channel_low
        else:
            return Signal.flat("ยังไม่ทะลุแชนแนล")

        atr = self.atr(window, self.atr_period)
        if atr <= 0:
            return Signal.flat("ATR ไม่ถูกต้อง")

        entry = last_close
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
                f"ราคาปิด {entry:.2f} ทะลุ{'จุดสูงสุด' if direction == Direction.BUY else 'จุดต่ำสุด'} "
                f"{self.dc_period} แท่ง ({broken_level:.2f}) เสนอ {direction.value} ตามสูตรเต่า"
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
            reason=f"Donchian{self.dc_period} breakout {'up' if direction == Direction.BUY else 'down'}",
            meta={"discussion": opinions},
        )

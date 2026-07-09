"""ทีม 8 "Dip Buyers" — pullback continuation (แนว Mark Minervini / William O'Neil)

หลักการ: อย่าไล่ราคา — รอเทรนด์ใหญ่ยืนยันก่อน (EMA50 เหนือ EMA200 และกำลังชันขึ้น)
แล้วซื้อตอนราคาย่อกลับมาแตะ EMA20 พอดี ("buy the dip in an uptrend") ได้ราคาต้นทุนดี
ในทิศทางที่ตลาดใหญ่หนุนอยู่แล้ว — ขาลงกลับด้าน
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


def _make_depth_analyst(name: str, max_depth_atr: float = 1.0) -> CommitteeMember:
    """ย่อตื้นๆ = healthy pullback, ดิ่งทะลุลึก = เทรนด์อาจกำลังพัง ห้ามรับ"""

    def check(ctx: dict) -> tuple[bool, str]:
        depth_atr = ctx["pullback_depth"] / ctx["atr"] if ctx["atr"] > 0 else 99
        if depth_atr > max_depth_atr:
            return False, f"ย่อลึก {depth_atr:.1f} ATR เลย EMA20 (>{max_depth_atr}) เทรนด์อาจพัง ค้าน"
        return True, f"ย่อแค่ {depth_atr:.1f} ATR เป็น pullback สุขภาพดี"

    return CommitteeMember(name, "Depth Analyst", check)


@register_strategy
class TrendPullbackStrategy(Strategy):
    name = "trend_pullback"
    description = (
        "Pullback continuation (แนว Minervini/O'Neil): รอเทรนด์ใหญ่ยืนยัน (EMA50 อยู่ฝั่งเดียว "
        "กับ EMA200 และชันไปทางนั้น) แล้วเข้าเมื่อราคาย่อกลับมาแตะ EMA20 แล้วปิดกลับฝั่งเทรนด์ "
        "— ได้ราคาต้นทุนดีในทิศที่ตลาดหนุน SL 1.5×ATR TP 3×ATR ปฏิเสธ pullback ที่ดิ่งลึกเกิน "
        "(สัญญาณเทรนด์กำลังพัง)"
    )

    def __init__(
        self,
        fast_ema: int = 20,
        mid_ema: int = 50,
        slow_ema: int = 200,
        slope_bars: int = 6,
        atr_period: int = 14,
        atr_mult_sl: float = 1.5,
        atr_mult_tp: float = 3.0,
    ):
        self.fast_ema = fast_ema
        self.mid_ema = mid_ema
        self.slow_ema = slow_ema
        self.slope_bars = slope_bars
        self.atr_period = atr_period
        self.atr_mult_sl = atr_mult_sl
        self.atr_mult_tp = atr_mult_tp
        self._committee = Committee(
            [
                make_proposer("ดีลเลอร์ดิพ"),
                make_trend_analyst("โค้ชเทรนด์", mode="need_trend", adx_threshold=18.0),
                _make_depth_analyst("นางฟ้าดีพ"),
                make_risk_officer("หมวดเสี่ยง", min_rr=1.5),
                make_session_analyst("ปู่โมง"),
            ]
        )

    def min_lookback(self) -> int:
        return self.slow_ema + 30

    def evaluate(self, data: MarketData, idx: int) -> Signal:
        lookback = self.min_lookback()
        if idx < lookback:
            return Signal.flat("ข้อมูลไม่พอ (warmup)")

        window = data.window(idx, lookback)
        close = window["close"]

        ema20 = close.ewm(span=self.fast_ema, adjust=False).mean()
        ema50 = close.ewm(span=self.mid_ema, adjust=False).mean()
        ema200 = close.ewm(span=self.slow_ema, adjust=False).mean()

        e20, e50, e200 = float(ema20.iloc[-1]), float(ema50.iloc[-1]), float(ema200.iloc[-1])
        e50_slope = float(ema50.iloc[-1] - ema50.iloc[-self.slope_bars])

        last_close = float(close.iloc[-1])
        last_low = float(window["low"].iloc[-1])
        last_high = float(window["high"].iloc[-1])

        atr = self.atr(window, self.atr_period)
        if atr <= 0:
            return Signal.flat("ATR ไม่ถูกต้อง")

        uptrend = e50 > e200 and e50_slope > 0
        downtrend = e50 < e200 and e50_slope < 0

        if uptrend and last_low <= e20 and last_close > e20:
            direction = Direction.BUY
            pullback_depth = e20 - last_low  # ย่อลึกใต้ EMA20 แค่ไหน
        elif downtrend and last_high >= e20 and last_close < e20:
            direction = Direction.SELL
            pullback_depth = last_high - e20
        else:
            return Signal.flat("ไม่มีเทรนด์ชัด หรือราคายังไม่ย่อกลับมาแตะ EMA20")

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
                f"เทรนด์{'ขึ้น' if direction == Direction.BUY else 'ลง'}ยืนยัน "
                f"(EMA50 {e50:.2f} vs EMA200 {e200:.2f}) ราคาย่อแตะ EMA20 ({e20:.2f}) "
                f"แล้วปิดกลับฝั่งเทรนด์ที่ {entry:.2f} เสนอ {direction.value}"
            ),
            pullback_depth=pullback_depth,
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
            reason=f"Pullback to EMA{self.fast_ema} in {'up' if direction == Direction.BUY else 'down'}trend",
            meta={"discussion": opinions},
        )

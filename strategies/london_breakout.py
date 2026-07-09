"""ทีม 4 "Session Raiders" — London breakout (สำนัก session trading ของนักเทรด FX/ทอง intraday)

หลักการ: ช่วงตลาดเอเชียทองมักแกว่งในกรอบแคบ พอ London เปิด สภาพคล่องพุ่ง ราคามักหลุด
กรอบเอเชียแล้ววิ่งต่อ — เข้าตามทิศที่หลุด SL ที่กลางกรอบ TP หนึ่งเท่าของความกว้างกรอบ
(เวลาโบรก GMT+2/+3: เอเชีย ~01:00-08:59, London เปิด ~09:00-10:00)
"""
from __future__ import annotations

from core.committee import (
    Committee,
    CommitteeMember,
    make_bias_analyst,
    make_proposer,
    make_risk_officer,
)
from core.signal import Direction, MarketData, Signal
from core.strategy import Strategy, register_strategy


def _make_range_quality_analyst(
    name: str, min_atr_mult: float = 0.8, max_atr_mult: float = 4.0
) -> CommitteeMember:
    """กรอบเอเชียต้องไม่แคบจนไร้ความหมาย และไม่กว้างจน SL ที่กลางกรอบเสี่ยงเกิน"""

    def check(ctx: dict) -> tuple[bool, str]:
        width_atr = ctx["range_width"] / ctx["atr"] if ctx["atr"] > 0 else 0
        if width_atr < min_atr_mult:
            return False, f"กรอบเอเชียแคบแค่ {width_atr:.1f} ATR (<{min_atr_mult}) หลุดง่ายไร้นัย ค้าน"
        if width_atr > max_atr_mult:
            return False, f"กรอบเอเชียกว้าง {width_atr:.1f} ATR (>{max_atr_mult}) SL ไกลเกิน ค้าน"
        return True, f"กรอบกว้าง {width_atr:.1f} ATR อยู่ในโซนคุณภาพ"

    return CommitteeMember(name, "Range Quality Analyst", check)


def _make_freshness_analyst(name: str, last_good_hour: int = 12) -> CommitteeMember:
    """ยิ่งสายโมเมนตัม breakout ยิ่งอ่อน — อนุมัติเฉพาะช่วงเช้าของ London"""

    def check(ctx: dict) -> tuple[bool, str]:
        hour = ctx["bar_time"].hour
        if hour > last_good_hour:
            return False, f"ตอนนี้ {hour:02d}:00 เลยช่วงพลัง London เปิดแล้ว โมเมนตัมอ่อน ค้าน"
        return True, f"ตอนนี้ {hour:02d}:00 ยังอยู่ในช่วงพลังของ London"

    return CommitteeMember(name, "Timing Analyst", check)


@register_strategy
class LondonBreakoutStrategy(Strategy):
    name = "london_breakout"
    description = (
        "Session breakout สำนักเทรด intraday: ตีกรอบสูง-ต่ำช่วงตลาดเอเชีย (01:00-08:59 เวลาโบรก) "
        "แล้วเข้าตามทิศที่ราคาหลุดกรอบช่วง London เปิด (09:00-13:00) — SL ที่กึ่งกลางกรอบ "
        "TP หนึ่งเท่าของความกว้างกรอบ (R:R ~1:2) เหมาะกับวันที่ London มีทิศทางชัด"
    )

    def __init__(
        self,
        asia_start: int = 1,
        asia_end: int = 8,
        trade_start: int = 9,
        trade_end: int = 13,
        min_asia_bars: int = 6,
        max_late_entry_atr: float = 0.5,
        breakout_buffer_atr: float = 0.0,  # ต้องปิดพ้นกรอบเกินกี่ ATR ถึงนับ (กัน false breakout ใน TF เล็ก)
        atr_period: int = 14,
    ):
        self.asia_start = asia_start
        self.asia_end = asia_end
        self.trade_start = trade_start
        self.trade_end = trade_end
        self.min_asia_bars = min_asia_bars
        self.max_late_entry_atr = max_late_entry_atr
        self.breakout_buffer_atr = breakout_buffer_atr
        self.atr_period = atr_period
        self._committee = Committee(
            [
                make_proposer("เจมส์ลอนดอน"),
                _make_range_quality_analyst("แม่หมอกรอบ"),
                make_bias_analyst("ลุงไบแอส"),
                make_risk_officer("ยามประตู", min_rr=1.2),
                _make_freshness_analyst("นายนาที"),
            ]
        )

    def min_lookback(self) -> int:
        return 80  # ครอบคลุม ~3 วันเทรด พอให้เห็นกรอบเอเชียของวันปัจจุบันเต็มๆ

    def evaluate(self, data: MarketData, idx: int) -> Signal:
        lookback = self.min_lookback()
        if idx < lookback:
            return Signal.flat("ข้อมูลไม่พอ (warmup)")

        window = data.window(idx, lookback)
        bar_time = window.index[-1]
        hour = bar_time.hour

        if not (self.trade_start <= hour <= self.trade_end):
            return Signal.flat("นอกช่วงเวลาเทรดของทีม (09:00-13:00)")

        today = window.index.date == bar_time.date()
        hours = window.index.hour
        asia_mask = today & (hours >= self.asia_start) & (hours <= self.asia_end)
        asia_bars = window[asia_mask]
        if len(asia_bars) < self.min_asia_bars:
            return Signal.flat("กรอบเอเชียวันนี้ข้อมูลไม่ครบ")

        range_high = float(asia_bars["high"].max())
        range_low = float(asia_bars["low"].min())
        range_mid = (range_high + range_low) / 2
        range_width = range_high - range_low

        prev_close = float(window["close"].iloc[-2])
        last_close = float(window["close"].iloc[-1])

        atr = self.atr(window, self.atr_period)
        if atr <= 0 or range_width <= 0:
            return Signal.flat("ATR/กรอบ ไม่ถูกต้อง")

        buffer = atr * self.breakout_buffer_atr
        threshold_up = range_high + buffer
        threshold_down = range_low - buffer

        if prev_close <= threshold_up < last_close:
            direction = Direction.BUY
            if last_close - threshold_up > atr * self.max_late_entry_atr:
                return Signal.flat("ราคาวิ่งเลยกรอบไปไกลแล้ว เข้าช้าเกิน")
            sl, tp = range_mid, last_close + range_width
        elif prev_close >= threshold_down > last_close:
            direction = Direction.SELL
            if threshold_down - last_close > atr * self.max_late_entry_atr:
                return Signal.flat("ราคาวิ่งเลยกรอบไปไกลแล้ว เข้าช้าเกิน")
            sl, tp = range_mid, last_close - range_width
        else:
            return Signal.flat("ยังไม่หลุดกรอบเอเชีย")

        # bias โครงสร้างจากความชัน EMA50 (ให้ Structure Analyst ใช้โหวต)
        ema50 = window["close"].ewm(span=50, adjust=False).mean()
        slope = float(ema50.iloc[-1] - ema50.iloc[-10])
        ema_bias = 0 if abs(slope) < 0.05 * atr else (1 if slope > 0 else -1)

        ctx = self.build_ctx(
            window=window,
            bar_time=bar_time,
            direction=direction,
            entry=last_close,
            sl=sl,
            tp=tp,
            atr=atr,
            setup_comment=(
                f"ราคาหลุดกรอบเอเชีย ({range_low:.2f}-{range_high:.2f} กว้าง {range_width:.2f}) "
                f"ฝั่ง{'บน' if direction == Direction.BUY else 'ล่าง'} ที่ {last_close:.2f} เสนอ {direction.value}"
            ),
            range_width=range_width,
            ema_bias=ema_bias,
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
            reason=f"London breakout {'up' if direction == Direction.BUY else 'down'} "
            f"(กรอบเอเชีย {range_low:.2f}-{range_high:.2f})",
            meta={"discussion": opinions},
        )

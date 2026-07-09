"""ทีม 10 "Level Keepers" — support/resistance bounce (สำนัก price action ล้วน)

หลักการ: ระดับราคาที่เคยกลับตัวหลายครั้ง (แนวรับ/แนวต้าน) มีคำสั่งซื้อขายรออยู่จริง
เมื่อราคากลับมาแตะระดับพร้อมแท่งปฏิเสธ (rejection candle มีไส้ยาว) = ระดับยังทำงาน
เข้าเด้งตามระดับ — ไม่ใช้ indicator เลย ใช้โครงสร้างราคาล้วนๆ
"""
from __future__ import annotations

from core.committee import (
    Committee,
    CommitteeMember,
    make_proposer,
    make_risk_officer,
    make_session_analyst,
)
from core.signal import Direction, MarketData, Signal
from core.strategy import Strategy, register_strategy
from strategies.rsi_divergence import _find_pivots


def _make_level_strength_analyst(name: str, min_touches: int = 2) -> CommitteeMember:
    """ระดับที่แตะครั้งเดียวอาจเป็นแค่จุดสุ่ม — ต้องเคยกลับตัว >= min_touches ครั้งถึงน่าเชื่อ"""

    def check(ctx: dict) -> tuple[bool, str]:
        touches = ctx["level_touches"]
        if touches < min_touches:
            return False, f"ระดับนี้เคยแตะแค่ {touches} ครั้ง (<{min_touches}) ยังพิสูจน์ตัวเองไม่พอ ค้าน"
        return True, f"ระดับนี้เคยกลับตัวแล้ว {touches} ครั้ง เป็นระดับที่ตลาดเคารพจริง"

    return CommitteeMember(name, "Level Strength Analyst", check)


def _make_candle_quality_analyst(name: str, min_wick_ratio: float = 0.4) -> CommitteeMember:
    """แท่งปฏิเสธที่ดีต้องมีไส้ยาว = มีแรงสู้กลับจริงที่ระดับ ไม่ใช่แค่ราคาผ่านมาแตะ"""

    def check(ctx: dict) -> tuple[bool, str]:
        wick_ratio = ctx["wick_ratio"]
        if wick_ratio < min_wick_ratio:
            return False, f"ไส้ปฏิเสธแค่ {wick_ratio:.0%} ของแท่ง (<{min_wick_ratio:.0%}) แรงสู้กลับอ่อน ค้าน"
        return True, f"ไส้ปฏิเสธยาว {wick_ratio:.0%} ของแท่ง มีแรงสู้กลับที่ระดับจริง"

    return CommitteeMember(name, "Candle Quality Analyst", check)


@register_strategy
class SRBounceStrategy(Strategy):
    name = "sr_bounce"
    description = (
        "Support/Resistance bounce สำนัก price action ล้วน (ไม่ใช้ indicator): หาระดับจาก pivot "
        "จริงย้อนหลัง เข้า BUY เมื่อราคาย่อมาแตะแนวรับพร้อมแท่งปฏิเสธไส้ล่างยาว (แรงซื้อสู้กลับ), "
        "SELL ที่แนวต้านกลับด้าน — SL ใต้/เหนือระดับ TP 2×ATR คณะกรรมการเข้มเรื่องความแข็ง "
        "ของระดับ (ต้องเคยกลับตัว ≥2 ครั้ง) และคุณภาพแท่งปฏิเสธ"
    )

    def __init__(
        self,
        pivot_lookback: int = 120,
        pivot_wing: int = 2,
        touch_tolerance_atr: float = 0.4,
        cluster_tolerance_atr: float = 0.5,
        min_wick_ratio_setup: float = 0.25,
        atr_period: int = 14,
        sl_pad_atr: float = 0.8,
        atr_mult_tp: float = 2.0,
    ):
        self.pivot_lookback = pivot_lookback
        self.pivot_wing = pivot_wing
        self.touch_tolerance_atr = touch_tolerance_atr
        self.cluster_tolerance_atr = cluster_tolerance_atr
        self.min_wick_ratio_setup = min_wick_ratio_setup
        self.atr_period = atr_period
        self.sl_pad_atr = sl_pad_atr
        self.atr_mult_tp = atr_mult_tp
        self._committee = Committee(
            [
                make_proposer("ช่างเลเวล"),
                _make_level_strength_analyst("นักนับรอบ"),
                _make_candle_quality_analyst("หมอแท่งเทียน"),
                make_risk_officer("ผู้คุมทุน", min_rr=1.2),
                make_session_analyst("เฝ้ายาม"),
            ]
        )

    def min_lookback(self) -> int:
        return self.pivot_lookback + self.atr_period + 10

    def evaluate(self, data: MarketData, idx: int) -> Signal:
        lookback = self.min_lookback()
        if idx < lookback:
            return Signal.flat("ข้อมูลไม่พอ (warmup)")

        window = data.window(idx, lookback)
        atr = self.atr(window, self.atr_period)
        if atr <= 0:
            return Signal.flat("ATR ไม่ถูกต้อง")

        bar_open = float(window["open"].iloc[-1])
        bar_close = float(window["close"].iloc[-1])
        bar_high = float(window["high"].iloc[-1])
        bar_low = float(window["low"].iloc[-1])
        bar_range = bar_high - bar_low
        if bar_range <= 0:
            return Signal.flat("แท่งปัจจุบันไม่มี range")

        # --- เด้งจากแนวรับ (BUY): แท่งเขียว + ไส้ล่างยาว + low แตะระดับ pivot low เดิม ---
        low_pivot_idx = _find_pivots(window["low"], is_low=True, wing=self.pivot_wing)
        support_levels = [float(window["low"].iloc[j]) for j in low_pivot_idx[:-1]]  # ไม่รวม pivot สดที่อาจเป็นแท่งนี้เอง
        lower_wick = min(bar_open, bar_close) - bar_low
        if bar_close > bar_open and support_levels:
            nearest = min(support_levels, key=lambda level: abs(bar_low - level))
            if abs(bar_low - nearest) <= atr * self.touch_tolerance_atr:
                wick_ratio = lower_wick / bar_range
                if wick_ratio >= self.min_wick_ratio_setup:
                    touches = sum(
                        1 for level in support_levels
                        if abs(level - nearest) <= atr * self.cluster_tolerance_atr
                    )
                    direction = Direction.BUY
                    entry = bar_close
                    sl = nearest - atr * self.sl_pad_atr
                    tp = entry + atr * self.atr_mult_tp
                    return self._review(
                        window, direction, entry, sl, tp, atr, nearest, touches, wick_ratio,
                        kind="แนวรับ",
                    )

        # --- เด้งจากแนวต้าน (SELL): แท่งแดง + ไส้บนยาว + high แตะระดับ pivot high เดิม ---
        high_pivot_idx = _find_pivots(window["high"], is_low=False, wing=self.pivot_wing)
        resistance_levels = [float(window["high"].iloc[j]) for j in high_pivot_idx[:-1]]
        upper_wick = bar_high - max(bar_open, bar_close)
        if bar_close < bar_open and resistance_levels:
            nearest = min(resistance_levels, key=lambda level: abs(bar_high - level))
            if abs(bar_high - nearest) <= atr * self.touch_tolerance_atr:
                wick_ratio = upper_wick / bar_range
                if wick_ratio >= self.min_wick_ratio_setup:
                    touches = sum(
                        1 for level in resistance_levels
                        if abs(level - nearest) <= atr * self.cluster_tolerance_atr
                    )
                    direction = Direction.SELL
                    entry = bar_close
                    sl = nearest + atr * self.sl_pad_atr
                    tp = entry - atr * self.atr_mult_tp
                    return self._review(
                        window, direction, entry, sl, tp, atr, nearest, touches, wick_ratio,
                        kind="แนวต้าน",
                    )

        return Signal.flat("ไม่มีการเด้งจากระดับสำคัญพร้อมแท่งปฏิเสธ")

    def _review(self, window, direction, entry, sl, tp, atr, level, touches, wick_ratio, kind) -> Signal:
        ctx = self.build_ctx(
            window=window,
            bar_time=window.index[-1],
            direction=direction,
            entry=entry,
            sl=sl,
            tp=tp,
            atr=atr,
            setup_comment=(
                f"ราคาแตะ{kind} {level:.2f} แล้วเกิดแท่งปฏิเสธ (ไส้ {wick_ratio:.0%} ของแท่ง) "
                f"ระดับนี้เคยกลับตัว {touches} ครั้ง เสนอ {direction.value} ที่ {entry:.2f}"
            ),
            level_touches=touches,
            wick_ratio=wick_ratio,
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
            reason=f"S/R bounce ที่{kind} {level:.2f} (แตะแล้ว {touches} ครั้ง)",
            meta={"discussion": opinions},
        )

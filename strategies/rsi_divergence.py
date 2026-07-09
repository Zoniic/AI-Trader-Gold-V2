"""ทีม 6 "Divergence Hunters" — RSI divergence reversal (ต่อยอดจากงานของ J. Welles Wilder)

หลักการ: ราคาทำจุดต่ำใหม่แต่ RSI ไม่ทำจุดต่ำใหม่ตาม (bullish divergence) = แรงขายอ่อนล้า
รอราคาเริ่มกลับตัวแล้วเข้าสวน — จุดกลับตัวใหญ่มักเกิดแบบนี้ แต่ต้องรอ setup นานกว่าทีมอื่น
ใช้ pivot ที่ยืนยันแล้วเท่านั้น (ต้องมีแท่งปิดสองข้าง) กัน lookahead
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


def _make_extremeness_analyst(
    name: str, bull_max_rsi: float = 40.0, bear_min_rsi: float = 60.0
) -> CommitteeMember:
    """Divergence น่าเชื่อเฉพาะที่เกิดในโซนสุดโต่ง — กลางกราฟคือ noise"""

    def check(ctx: dict) -> tuple[bool, str]:
        pivot_rsi = ctx["pivot_rsi"]
        if ctx["direction"].sign > 0:
            if pivot_rsi <= bull_max_rsi:
                return True, f"RSI ที่จุด pivot {pivot_rsi:.1f} อยู่โซน oversold divergence น่าเชื่อ"
            return False, f"RSI ที่ pivot {pivot_rsi:.1f} ไม่ถึงโซนสุดโต่ง (≤{bull_max_rsi:.0f}) ค้าน"
        if pivot_rsi >= bear_min_rsi:
            return True, f"RSI ที่จุด pivot {pivot_rsi:.1f} อยู่โซน overbought divergence น่าเชื่อ"
        return False, f"RSI ที่ pivot {pivot_rsi:.1f} ไม่ถึงโซนสุดโต่ง (≥{bear_min_rsi:.0f}) ค้าน"

    return CommitteeMember(name, "Extremeness Analyst", check)


def _find_pivots(series, is_low: bool, wing: int = 2) -> list[int]:
    """หา pivot ที่ยืนยันแล้ว (มีแท่งปิดครบสองข้าง) — คืน positional index ใน series"""
    vals = series.to_numpy()
    pivots = []
    for j in range(wing, len(vals) - wing):
        left = vals[j - wing : j]
        right = vals[j + 1 : j + 1 + wing]
        if is_low and vals[j] < left.min() and vals[j] < right.min():
            pivots.append(j)
        elif not is_low and vals[j] > left.max() and vals[j] > right.max():
            pivots.append(j)
    return pivots


@register_strategy
class RSIDivergenceStrategy(Strategy):
    name = "rsi_divergence"
    description = (
        "Divergence reversal (ต่อยอดแนวคิด RSI ของ J. Welles Wilder): เข้า BUY เมื่อราคาทำ "
        "จุดต่ำใหม่แต่ RSI ยกต่ำขึ้น (bullish divergence = แรงขายอ่อนล้า) และราคาเริ่มเด้ง, "
        "SELL กลับด้าน — SL ใต้จุด pivot ล่าสุด TP สองเท่าของระยะเสี่ยง (R:R 1:2) "
        "ใช้จับจุดกลับตัวใหญ่ เทรดไม่บ่อยแต่หวังไม้คุณภาพ"
    )

    def __init__(
        self,
        rsi_period: int = 14,
        pivot_wing: int = 2,
        max_pivot_age: int = 12,
        min_rsi_gap: float = 2.0,
        lookback_bars: int = 70,
        atr_period: int = 14,
        sl_pad_atr: float = 0.5,
        rr_multiple: float = 2.0,
    ):
        self.rsi_period = rsi_period
        self.pivot_wing = pivot_wing
        self.max_pivot_age = max_pivot_age
        self.min_rsi_gap = min_rsi_gap
        self.lookback_bars = lookback_bars
        self.atr_period = atr_period
        self.sl_pad_atr = sl_pad_atr
        self.rr_multiple = rr_multiple
        self._committee = Committee(
            [
                make_proposer("นักล่าดิฟ"),
                _make_extremeness_analyst("แม่นเขต"),
                make_trend_analyst("เสี่ยชิล", mode="need_quiet", adx_threshold=35.0),
                make_risk_officer("ครูริส", min_rr=1.2),
                make_session_analyst("เจ้าเวลา"),
            ]
        )

    def min_lookback(self) -> int:
        return self.lookback_bars + self.atr_period + 10

    def evaluate(self, data: MarketData, idx: int) -> Signal:
        lookback = self.min_lookback()
        if idx < lookback:
            return Signal.flat("ข้อมูลไม่พอ (warmup)")

        window = data.window(idx, lookback)
        close = window["close"]
        rsi_series = self.rsi(close, self.rsi_period)
        n = len(window)

        atr = self.atr(window, self.atr_period)
        if atr <= 0:
            return Signal.flat("ATR ไม่ถูกต้อง")

        entry = float(close.iloc[-1])
        prev_close = float(close.iloc[-2])

        # --- bullish divergence: ราคา lower low แต่ RSI higher low ---
        low_pivots = _find_pivots(window["low"], is_low=True, wing=self.pivot_wing)
        if len(low_pivots) >= 2:
            p1, p2 = low_pivots[-1], low_pivots[-2]  # p1 ใหม่กว่า
            price_ll = window["low"].iloc[p1] < window["low"].iloc[p2]
            rsi_hl = rsi_series.iloc[p1] > rsi_series.iloc[p2] + self.min_rsi_gap
            fresh = (n - 1 - p1) <= self.max_pivot_age
            turning_up = entry > prev_close
            if price_ll and rsi_hl and fresh and turning_up:
                direction = Direction.BUY
                sl = float(window["low"].iloc[p1]) - atr * self.sl_pad_atr
                risk = entry - sl
                if risk > 0:
                    tp = entry + risk * self.rr_multiple
                    return self._review(
                        window, direction, entry, sl, tp, atr,
                        pivot_rsi=float(rsi_series.iloc[p1]),
                        detail=(
                            f"ราคาทำ lower low ({window['low'].iloc[p2]:.2f}→{window['low'].iloc[p1]:.2f}) "
                            f"แต่ RSI ยกขึ้น ({rsi_series.iloc[p2]:.1f}→{rsi_series.iloc[p1]:.1f}) "
                            f"bullish divergence + ราคาเริ่มเด้ง เสนอ BUY"
                        ),
                    )

        # --- bearish divergence: ราคา higher high แต่ RSI lower high ---
        high_pivots = _find_pivots(window["high"], is_low=False, wing=self.pivot_wing)
        if len(high_pivots) >= 2:
            p1, p2 = high_pivots[-1], high_pivots[-2]
            price_hh = window["high"].iloc[p1] > window["high"].iloc[p2]
            rsi_lh = rsi_series.iloc[p1] < rsi_series.iloc[p2] - self.min_rsi_gap
            fresh = (n - 1 - p1) <= self.max_pivot_age
            turning_down = entry < prev_close
            if price_hh and rsi_lh and fresh and turning_down:
                direction = Direction.SELL
                sl = float(window["high"].iloc[p1]) + atr * self.sl_pad_atr
                risk = sl - entry
                if risk > 0:
                    tp = entry - risk * self.rr_multiple
                    return self._review(
                        window, direction, entry, sl, tp, atr,
                        pivot_rsi=float(rsi_series.iloc[p1]),
                        detail=(
                            f"ราคาทำ higher high ({window['high'].iloc[p2]:.2f}→{window['high'].iloc[p1]:.2f}) "
                            f"แต่ RSI กดลง ({rsi_series.iloc[p2]:.1f}→{rsi_series.iloc[p1]:.1f}) "
                            f"bearish divergence + ราคาเริ่มพับ เสนอ SELL"
                        ),
                    )

        return Signal.flat("ไม่พบ divergence ที่สดใหม่พอ")

    def _review(self, window, direction, entry, sl, tp, atr, pivot_rsi, detail) -> Signal:
        ctx = self.build_ctx(
            window=window,
            bar_time=window.index[-1],
            direction=direction,
            entry=entry,
            sl=sl,
            tp=tp,
            atr=atr,
            setup_comment=detail,
            pivot_rsi=pivot_rsi,
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
            reason=f"RSI divergence {'bullish' if direction == Direction.BUY else 'bearish'}",
            meta={"discussion": opinions},
        )

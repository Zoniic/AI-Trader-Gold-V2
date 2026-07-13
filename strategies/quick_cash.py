"""ทีม 14 "เก็บเงินด่วน" (Quick Cash) — สายซิ่งแบบมีวินัย: เข้าไว ออกไว เก็บกำไรเรื่อยๆ

บทเรียนจากสายซิ่ง 2 ทีมก่อนหน้า (momentum_scalper PF<0.87 ทุก config, rule_breaker M15 PF 0.32):
TF เล็ก + TP เล็กกว่า 1×ATR = ต้นทุน spread กินหมด ไม่รอด ทีมนี้จึงซิ่งคนละแบบ —
"ซิ่งที่การออก ไม่ใช่ที่ขนาด TP":
- เข้าเมื่อเกิด momentum burst ชัดๆ เท่านั้น: แท่ง body ใหญ่ (>60% ของ range) ปิดทะลุ
  จุดสูง/ต่ำสุด 10 แท่งล่าสุด = แรงซื้อ/ขายจริงกำลังมา ไม่ใช่เดาจุดกลับตัว
- TP 1.4×ATR / SL 0.9×ATR (R:R ~1:1.6 — ใหญ่พอสู้ต้นทุน ต่างจากสายซิ่งรุ่นก่อน)
- ออกไว: partial 60% ที่ 0.7R แล้วเลื่อน BE ทันที + trailing แน่น 0.7R
  → ไม้ส่วนใหญ่จบเร็วภายในไม่กี่แท่ง เก็บกำไรก้อนเล็กๆ สม่ำเสมอตามสไตล์สายซิ่ง
- ไม่ถือข้ามช่วงตลาดเงียบ: คณะกรรมการกรอง session + volatility เข้มเพราะ burst
  ปลอมเกิดบ่อยตอนสภาพคล่องบาง
"""
from __future__ import annotations

import pandas as pd

from core.committee import (
    Committee,
    CommitteeMember,
    make_proposer,
    make_risk_officer,
    make_session_analyst,
    make_volatility_analyst,
)
from core.signal import Direction, MarketData, Signal
from core.strategy import Strategy, register_strategy


def _make_burst_quality_analyst(name: str, min_body_ratio: float = 0.6) -> CommitteeMember:
    """แท่ง burst ต้องเป็นแท่งคุณภาพ — body ใหญ่เทียบ range ทั้งแท่ง (ไม่ใช่หางยาวไส้กลวง)
    หางยาว = โดนปฏิเสธราคา แปลว่าแรงไม่จริง เข้าตามไปเสี่ยงโดนสวนทันที
    """

    def check(ctx: dict) -> tuple[bool, str]:
        body_ratio = ctx.get("body_ratio", 0.0)
        if body_ratio < min_body_ratio:
            return False, (
                f"แท่ง burst มี body แค่ {body_ratio:.0%} ของ range (< {min_body_ratio:.0%}) "
                "หางยาวเกิน แรงไม่จริง ค้าน"
            )
        return True, f"แท่ง burst คุณภาพดี body {body_ratio:.0%} ของ range — แรงจริง"

    return CommitteeMember(name, "Burst Quality Analyst", check)


@register_strategy
class QuickCashStrategy(Strategy):
    name = "quick_cash"
    description = (
        "สายซิ่งมีวินัย — เข้าไวเมื่อเกิด momentum burst (แท่ง body >60% ปิดทะลุจุดสูง/ต่ำ 10 แท่ง) "
        "ออกไว: partial 60% ที่ 0.7R + BE ทันที + trailing แน่น เก็บกำไรก้อนเล็กสม่ำเสมอ "
        "TP 1.4×ATR / SL 0.9×ATR — บทเรียนจากสายซิ่งรุ่นก่อน: TP ต้องใหญ่พอสู้ต้นทุน "
        "ซิ่งที่ความเร็วการออก ไม่ใช่ขนาดเป้า ออกแบบสำหรับ M15/M30"
    )

    def __init__(
        self,
        breakout_period: int = 10,
        min_body_ratio: float = 0.6,
        atr_period: int = 14,
        atr_mult_sl: float = 0.9,
        atr_mult_tp: float = 1.4,
        min_atr_pct: float = 0.05,
    ):
        self.breakout_period = breakout_period
        self.min_body_ratio = min_body_ratio
        self.atr_period = atr_period
        self.atr_mult_sl = atr_mult_sl
        self.atr_mult_tp = atr_mult_tp
        self.min_atr_pct = min_atr_pct  # ATR ต้องไม่เล็กเกิน (% ของราคา) กันซิ่งตอนตลาดตาย
        self._committee = Committee(
            [
                make_proposer("เจ้าสัวด่วน"),
                _make_burst_quality_analyst("ตาไวแท่งเทียน", min_body_ratio=min_body_ratio),
                make_volatility_analyst("เจ๊เร็ว", max_spike_ratio=2.2),
                make_risk_officer("พี่เบรค", min_rr=1.2),
                make_session_analyst("นาฬิกาปลุก"),
            ]
        )

    def min_lookback(self) -> int:
        return max(self.breakout_period, self.atr_period) + 10

    def evaluate(self, data: MarketData, idx: int) -> Signal:
        lookback = self.min_lookback()
        if idx < lookback:
            return Signal.flat("ข้อมูลไม่พอ (warmup)")

        window = data.window(idx, lookback)
        close = window["close"]
        bar = window.iloc[-1]
        o, h, l, c = float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"])

        bar_range = h - l
        if bar_range <= 0:
            return Signal.flat("แท่งล่าสุด range เป็นศูนย์")
        body = abs(c - o)
        body_ratio = body / bar_range

        # เทรนด์ใหญ่จาก EMA ช้า + slope — ซิ่ง "ตามเทรนด์" เท่านั้น (บทเรียนรอบ 1-2: ตาม burst
        # เปล่าๆ บน M15 gold โดนสวนทันที ต้องมีเทรนด์ใหญ่หนุนหลังถึงรอด)
        ema_slow = close.ewm(span=50, adjust=False).mean()
        ema_fast = close.ewm(span=self.breakout_period, adjust=False).mean()
        slope = float(ema_slow.iloc[-1] - ema_slow.iloc[-6])
        ema_fast_now = float(ema_fast.iloc[-1])

        atr_early = self.atr(window, self.atr_period)
        if atr_early <= 0:
            return Signal.flat("ATR ไม่ถูกต้อง")

        # pullback แตะ EMA เร็วแล้วดีดกลับตามเทรนด์: แท่งก่อนหน้าแตะ/หลุด EMA เร็ว
        # แท่งล่าสุดปิดกลับฝั่งเทรนด์อย่างมีแรง (body ใหญ่)
        prev_bar = window.iloc[-2]
        prev_low, prev_high = float(prev_bar["low"]), float(prev_bar["high"])

        uptrend = slope > atr_early * 0.3
        downtrend = slope < -atr_early * 0.3

        if uptrend and prev_low <= ema_fast_now and c > o and c > ema_fast_now:
            direction = Direction.BUY
        elif downtrend and prev_high >= ema_fast_now and c < o and c < ema_fast_now:
            direction = Direction.SELL
        else:
            return Signal.flat("ไม่มี pullback-resume ตามเทรนด์ (เทรนด์ไม่ชัดหรือยังไม่ดีดกลับ)")

        atr = atr_early
        if atr / c * 100 < self.min_atr_pct:
            return Signal.flat(f"ATR {atr:.2f} เล็กเกิน ({atr/c*100:.3f}% ของราคา) ตลาดเงียบ ซิ่งไม่คุ้ม")

        sl = c - direction.sign * (atr * self.atr_mult_sl)
        tp = c + direction.sign * (atr * self.atr_mult_tp)

        ctx = self.build_ctx(
            window=window,
            bar_time=window.index[-1],
            direction=direction,
            entry=c,
            sl=sl,
            tp=tp,
            atr=atr,
            setup_comment=(
                f"pullback-resume {direction.value}: แตะ EMA{self.breakout_period} แล้วดีดกลับ "
                f"ตามเทรนด์ EMA50 (slope {slope:+.2f}) แท่งยืนยัน body {body_ratio:.0%} เสนอซิ่งเก็บสั้น"
            ),
            body_ratio=body_ratio,
        )
        approved, opinions = self._committee.review(ctx)
        if not approved:
            vetoes = [o_["member"] for o_ in opinions if not o_["approve"]]
            return Signal.flat(f"คณะกรรมการไม่อนุมัติ ({', '.join(vetoes)} ค้าน)")

        return Signal(
            direction=direction,
            entry=c,
            sl=sl,
            tp=tp,
            reason=f"quick pullback-resume: body {body_ratio:.0%} ดีดจาก EMA{self.breakout_period} ตามเทรนด์",
            meta={"discussion": opinions},
        )

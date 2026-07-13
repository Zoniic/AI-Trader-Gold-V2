"""ทีม 13 "นอกคอก" (Rule Breaker) — ล่า win rate สูง 80% ด้วยการกลับหัวสมการ R:R

ทีมอื่นทั้งลีกออกแบบด้วย R:R 1:1.5-2 ซึ่งคณิตศาสตร์บังคับให้ win rate อยู่โซน 40-60% เท่านั้น
(ดีสุดในลีกคือ sr_bounce M30 = 59.8%) ทีมนี้แหกกฎข้อนั้นตรงๆ: **TP เล็กกว่า SL** (เก็บสั้น
ยอมถือกว้าง) — TP 0.6×ATR / SL 1.5×ATR = R:R 1:0.4 จุดคุ้มทุนอยู่ที่ WR 71.4% ต้องชนะถี่จริงๆ
ถึงอยู่รอด จึงเข้าเฉพาะ setup ความน่าจะเป็นสูงสุด: RSI(2) สุดโต่งขั้นรุนแรง + ราคายืดออกจาก
EMA เกินปกติ (rubber band ตึงสุด) แล้วเก็บแค่การดีดกลับสั้นๆ ไม่โลภ

กฎที่แหก (ตั้งใจ ไม่ใช่ความผิดพลาด):
- ไม่กรอง regime — เทรดทุกสภาวะตลาด (ทีมอื่นถูกจำกัด regime ถนัด)
- Risk officer ยอม R:R ต่ำถึง 0.3 (ทีมอื่นบังคับ >= 0.7-1.5)
- เทรดสวนเทรนด์ได้เสมอ — ไม่มี bias analyst คอยห้าม
- ซิ่งก็ได้ ช้าก็ได้ — class เดียวรันทั้ง M15 (สายซิ่ง) และ H1 (สายช้า) ต่างกันแค่ config

สิ่งที่ไม่แหก: kill-switch / max daily loss / position sizing ยังคุมเหมือนเดิมทุกทีม
(แหกกฎการเข้าไม้ได้ แต่แหกกฎการอยู่รอดไม่ได้)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.committee import (
    Committee,
    CommitteeMember,
    make_proposer,
    make_risk_officer,
    make_volatility_analyst,
)
from core.signal import Direction, MarketData, Signal
from core.strategy import Strategy, register_strategy


def _make_stretch_analyst(name: str, min_stretch_atr: float = 1.0) -> CommitteeMember:
    """ยางยืดต้องตึงจริงถึงอนุมัติ — ราคาต้องยืดออกจาก EMA เกิน min_stretch_atr เท่าของ ATR
    (ยิ่งตึงยิ่งดีดแรง = หัวใจของ win rate สูงในท่า snap-back สั้นๆ)
    """

    def check(ctx: dict) -> tuple[bool, str]:
        stretch = ctx.get("stretch_atr", 0.0)
        if stretch < min_stretch_atr:
            return False, (
                f"ราคายืดจาก EMA แค่ {stretch:.2f} ATR (< {min_stretch_atr:.1f}) "
                "ยางยังไม่ตึงพอ ดีดกลับไม่แรง ค้าน"
            )
        return True, f"ยางตึง {stretch:.2f} ATR — ระยะดีดกลับสั้นๆ มีโอกาสสูง"

    return CommitteeMember(name, "Stretch Analyst", check)


def _make_exhaustion_analyst(name: str) -> CommitteeMember:
    """แท่งล่าสุดต้องแสดงอาการ "แรงหมด" — แท่งสวนทางเริ่มหด/หางยาว ไม่ใช่กำลังวิ่งแรงขึ้นเรื่อยๆ
    (กันการรับมีดหล่น: RSI(2) สุดโต่งแต่โมเมนตัมยังเร่ง = อย่าเพิ่งสวน)
    """

    def check(ctx: dict) -> tuple[bool, str]:
        body_now = ctx.get("body_now", 0.0)
        body_prev = ctx.get("body_prev", 0.0)
        if body_prev > 0 and body_now > body_prev * 1.5:
            return False, (
                f"แท่งล่าสุด body {body_now:.2f} ใหญ่กว่าแท่งก่อน {body_now/body_prev:.1f} เท่า "
                "— โมเมนตัมยังเร่งอยู่ รับมีดหล่นอันตราย ค้าน"
            )
        return True, "แรงขายเริ่มหมด (แท่งหดตัว) จังหวะดีดกลับใกล้แล้ว"

    return CommitteeMember(name, "Exhaustion Analyst", check)


@register_strategy
class RuleBreakerStrategy(Strategy):
    name = "rule_breaker"
    description = (
        "นอกคอก — ล่า win rate 80% ด้วย R:R กลับหัว (TP 0.6×ATR < SL 1.5×ATR, จุดคุ้มทุน WR 71%) "
        "เข้าเมื่อ RSI(2) สุดโต่งขั้นรุนแรง (<=10/>=90) + ราคายืดจาก EMA เกิน 1 ATR แล้วเก็บแค่ "
        "การดีดกลับสั้นๆ ไม่โลภ แหกกฎ: ไม่กรอง regime, ยอม R:R ต่ำ, สวนเทรนด์ได้เสมอ, "
        "รันได้ทั้งสายซิ่ง (M15) และสายช้า (H1) — แต่ kill-switch/risk cap ยังคุมเหมือนทุกทีม"
    )

    def __init__(
        self,
        rsi_period: int = 2,
        rsi_extreme_low: float = 10.0,
        rsi_extreme_high: float = 90.0,
        ema_period: int = 20,
        min_stretch_atr: float = 1.0,
        atr_period: int = 14,
        atr_mult_sl: float = 1.5,
        atr_mult_tp: float = 0.6,
    ):
        self.rsi_period = rsi_period
        self.rsi_extreme_low = rsi_extreme_low
        self.rsi_extreme_high = rsi_extreme_high
        self.ema_period = ema_period
        self.min_stretch_atr = min_stretch_atr
        self.atr_period = atr_period
        self.atr_mult_sl = atr_mult_sl
        self.atr_mult_tp = atr_mult_tp
        self._committee = Committee(
            [
                make_proposer("ฉลามนอกคอก"),
                _make_stretch_analyst("เสี่ยหนังยาง", min_stretch_atr=min_stretch_atr),
                _make_exhaustion_analyst("หมอจับชีพจร"),
                # แหกกฎ: ยอม R:R ต่ำถึง 0.3 — ทีมนี้ชนะด้วยความถี่ ไม่ใช่ R ใหญ่
                make_risk_officer("ผู้คุมกฎคนสุดท้าย", min_rr=0.3),
                # volatility สูงเกิน = spread กิน TP เล็กๆ หมด — ข้อนี้แหกไม่ได้เพราะ TP เล็กมาก
                make_volatility_analyst("เจ๊สายฟ้า", max_spike_ratio=2.5),
            ]
        )

    def min_lookback(self) -> int:
        return max(self.ema_period, self.atr_period) + self.rsi_period + 10

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
        last_close = float(close.iloc[-1])

        rsi = self._rsi(close)
        if rsi <= self.rsi_extreme_low:
            direction = Direction.BUY
        elif rsi >= self.rsi_extreme_high:
            direction = Direction.SELL
        else:
            return Signal.flat(f"RSI({self.rsi_period})={rsi:.0f} ยังไม่สุดโต่งพอ")

        atr = self.atr(window, self.atr_period)
        if atr <= 0:
            return Signal.flat("ATR ไม่ถูกต้อง")

        # ยางยืด: ราคาต้องยืดออกจาก EMA มากพอ (หน่วย ATR) ถึงคุ้มที่จะสวนเก็บดีดกลับ
        ema = float(close.ewm(span=self.ema_period, adjust=False).mean().iloc[-1])
        stretch_atr = abs(last_close - ema) / atr
        # ทิศ stretch ต้องตรงกับทิศไม้ (ยืดลง = BUY สวนขึ้น, ยืดขึ้น = SELL สวนลง)
        stretch_matches = (last_close < ema) if direction == Direction.BUY else (last_close > ema)
        if not stretch_matches:
            return Signal.flat("RSI สุดโต่งแต่ราคาอยู่ผิดฝั่ง EMA — ไม่ใช่ setup ยางยืด")

        sl = last_close - direction.sign * (atr * self.atr_mult_sl)
        tp = last_close + direction.sign * (atr * self.atr_mult_tp)

        # ข้อมูลให้ exhaustion analyst: ขนาด body แท่งล่าสุดเทียบแท่งก่อน
        body_now = abs(float(window["close"].iloc[-1]) - float(window["open"].iloc[-1]))
        body_prev = abs(float(window["close"].iloc[-2]) - float(window["open"].iloc[-2]))

        ctx = self.build_ctx(
            window=window,
            bar_time=window.index[-1],
            direction=direction,
            entry=last_close,
            sl=sl,
            tp=tp,
            atr=atr,
            setup_comment=(
                f"RSI({self.rsi_period})={rsi:.0f} สุดโต่ง + ราคายืดจาก EMA{self.ema_period} "
                f"{stretch_atr:.2f} ATR เสนอสวน {direction.value} เก็บดีดกลับสั้น "
                f"(TP {self.atr_mult_tp}×ATR / SL {self.atr_mult_sl}×ATR)"
            ),
            stretch_atr=stretch_atr,
            body_now=body_now,
            body_prev=body_prev,
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
            reason=f"rubber-band snap: RSI({self.rsi_period})={rsi:.0f} + stretch {stretch_atr:.1f} ATR",
            meta={"discussion": opinions},
        )

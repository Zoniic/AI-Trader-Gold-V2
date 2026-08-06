"""ทีม 16 "MIDAS" — Momentum Intelligence · Drawdown-Aware Sizing

Reverse-engineer จาก "Gold Bot 2026" (log จริง 1 ก.ค.-6 ส.ค. 2026) ตามสเปกที่ยืนยันแล้ว:
- F1: EMA ribbon 20/50/100/200 ให้ทิศ (+1 เรียงขึ้น / -1 เรียงลง / 0 พันกัน — ribbon เดิม ไม่ flip
  ไปมาง่าย มี hysteresis ในตัวอยู่แล้วโดยธรรมชาติของการเรียง 4 เส้น)
- F2: เมื่อ ribbon = 0 (ไม่มีทิศ) สลับไปเดินตาม Bollinger Bands (20, SMA, close, 2SD) — เข้าตามทิศ
  ที่ราคาปิดทะลุกรอบออกไป ("walking the bands")
- F3: BB width percentile < 25 (จาก 100 แท่งล่าสุด) = squeeze/sideways → ห้ามเทรดเด็ดขาด
  (ต้นเหตุใหญ่สุดของ DD ในบอทเดิม — ไม้ scalp แกว่งรอบ SMA20 ตอนตลาดไม่มีทิศ)
- SL: swing สวนทางล่าสุด (fractal, ไม่ใช่ ATR multiplier แบบทีมอื่น) — ตรงกับที่ log เดิมแสดง SL
  ซ้ำกันที่ระดับ swing เป๊ะ
- TP: "Option B" ตามสเปก — ตั้ง TP ที่ swing เป้าหมายถัดไปแล้วให้ partial_tp_r/trailing_stop_r
  ใน trade_management จัดการ 50/50 (ปิดจริงครึ่งนึงที่ TP, อีกครึ่ง trail ต่อ) แทนที่จะปล่อย TP
  เป็นตัวเลขหลอกแบบบอทเดิม (บอทเดิม log แสดงราคาปิด "เลย" TP เล็กน้อยทุกครั้ง = TP ไม่เคยทำงานจริง
  กำไรทั้งหมดมาจาก trailing — ทีมนี้เก็บ TP ไว้แบบมีความหมายแทน)

ข้อจำกัดที่ต้องระบุตรงๆ (สเปกต้นฉบับสมมติสถาปัตยกรรมที่ต่างจากโปรเจกต์นี้):
- P1-P11/pyramid/margin-level guard ในสเปก MIDAS v3 คือของระบบ MT5 EA แยกต่างหากที่ยิงหลายไม้
  ซ้อนกันได้ (pyramiding) และมี margin/equity ของ leverage account ให้ track ส่วน backtest/live
  ของโปรเจกต์นี้ (backtest/engine.py, execution/live_runner.py) เป็นสถาปัตยกรรม "ทีมละ 1 ไม้
  พร้อมกัน" (v1 ไม่ pyramiding — ดู process_bar) จึงไม่มี concept ไม้เติม/margin level ให้ guard
  เป็น structural mismatch ไม่ใช่ bug — เก็บไว้เป็น TODO ถ้าจะย้ายไปสถาปัตยกรรมใหม่ตามสเปกเต็ม
- Kelly fraction / equity-based sizing / profit-skimming (P9-P11): ระบบ risk ที่มีอยู่ใช้
  risk_per_trade_pct ของ balance ต่อไม้ (ไม่ใช่ full Kelly formula) — ตั้งค่า risk_per_trade_pct
  ต่ำแบบระมัดระวังใน config แทนการ implement Kelly optimizer เต็มรูป (นอกขอบเขตงานนี้)
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


def _make_squeeze_analyst(name: str) -> CommitteeMember:
    """F3 — บล็อกทันทีถ้า BB width อยู่ใน squeeze (percentile ต่ำ) ไม่ว่า F1/F2 จะให้สัญญาณอะไรมา
    นี่คือฟิลเตอร์ที่บอทเดิม "เว้นช่องไว้แต่ไม่เคยทำ" — เป็นตัวแก้ปัญหาใหญ่สุดของระบบเดิม
    """

    def check(ctx: dict) -> tuple[bool, str]:
        if ctx.get("squeeze", False):
            return False, (
                f"BB width percentile {ctx.get('width_pct', 0):.0f} < 25 — squeeze/sideways "
                "ตลาดไม่มีทิศชัด ค้าน (จุดที่บอทเดิมเสียเงินหนักสุด)"
            )
        return True, f"BB width percentile {ctx.get('width_pct', 0):.0f} — ไม่ squeeze ผ่าน"

    return CommitteeMember(name, "Squeeze Analyst (F3)", check)


def _make_ribbon_hysteresis_analyst(name: str) -> CommitteeMember:
    """กันเข้าไม้ซ้ำตอน ribbon ยังอยู่สถานะเดิม (ไม่ใช่แท่งแรกของสัญญาณใหม่) — mirror พฤติกรรม
    บอทเดิมที่สัญญาณค้างข้ามวันได้โดยไม่ยิงซ้ำทุกแท่ง
    """

    def check(ctx: dict) -> tuple[bool, str]:
        if not ctx.get("is_new_ribbon_signal", True):
            return False, "ribbon ยังอยู่สถานะเดิม (ไม่ใช่แท่งแรกของสัญญาณใหม่) ค้าน กันเข้าซ้ำ"
        return True, "แท่งแรกของสัญญาณ ribbon ใหม่ — ผ่าน"

    return CommitteeMember(name, "Ribbon Hysteresis Analyst", check)


@register_strategy
class MidasStrategy(Strategy):
    name = "midas"
    description = (
        "MIDAS (Momentum Intelligence · Drawdown-Aware Sizing) — reverse-engineer จาก Gold Bot 2026: "
        "F1 EMA ribbon 20/50/100/200 ให้ทิศ, F2 เดินตาม Bollinger Bands(20,2) เมื่อ ribbon พันกัน, "
        "F3 บล็อกเทรดเมื่อ BB width squeeze (percentile<25) — แก้จุดที่บอทเดิมเสียเงินหนักสุด "
        "SL จาก swing สวนทาง (ไม่ใช่ ATR) TP ที่ swing เป้าหมาย ให้ partial TP 50% + trailing "
        "runner อีกครึ่ง (Option B ตามสเปก แทนที่ TP หลอกของบอทเดิมที่ไม่เคยถูกใช้จริง)"
    )

    def __init__(
        self,
        ema_fast: int = 20,
        ema_mid1: int = 50,
        ema_mid2: int = 100,
        ema_slow: int = 200,
        bb_period: int = 20,
        bb_std: float = 2.0,
        width_lookback: int = 100,
        squeeze_percentile: float = 25.0,
        swing_lookback: int = 20,
        swing_left: int = 3,
        swing_right: int = 3,
        sl_buffer_atr: float = 0.2,
        atr_period: int = 14,
        min_target_rr: float = 2.0,
    ):
        self.ema_fast = ema_fast
        self.ema_mid1 = ema_mid1
        self.ema_mid2 = ema_mid2
        self.ema_slow = ema_slow
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.width_lookback = width_lookback
        self.squeeze_percentile = squeeze_percentile
        self.swing_lookback = swing_lookback
        self.swing_left = swing_left
        self.swing_right = swing_right
        self.sl_buffer_atr = sl_buffer_atr
        self.atr_period = atr_period
        self.min_target_rr = min_target_rr
        self._committee = Committee(
            [
                make_proposer("ราชามิดาส"),
                _make_squeeze_analyst("นักตรวจ BB Width"),
                _make_ribbon_hysteresis_analyst("นักจับจังหวะ Ribbon"),
                make_risk_officer("ผู้พิทักษ์ทุน", min_rr=1.0),
                make_session_analyst("นาฬิกาทราย"),
            ]
        )

    def min_lookback(self) -> int:
        return max(self.ema_slow, self.width_lookback + self.bb_period, self.swing_lookback) + 20

    def _ribbon(self, close: pd.Series) -> int:
        e20 = close.ewm(span=self.ema_fast, adjust=False).mean().iloc[-1]
        e50 = close.ewm(span=self.ema_mid1, adjust=False).mean().iloc[-1]
        e100 = close.ewm(span=self.ema_mid2, adjust=False).mean().iloc[-1]
        e200 = close.ewm(span=self.ema_slow, adjust=False).mean().iloc[-1]
        if e20 > e50 > e100 > e200:
            return 1
        if e20 < e50 < e100 < e200:
            return -1
        return 0

    def _ribbon_series_last2(self, close: pd.Series) -> tuple[int, int]:
        """ribbon ของแท่งล่าสุดและแท่งก่อนหน้า — ใช้เช็คว่าเป็นแท่งแรกของสัญญาณใหม่ (hysteresis)"""
        now = self._ribbon(close)
        prev = self._ribbon(close.iloc[:-1])
        return now, prev

    def _swing_extremes(self, window: pd.DataFrame) -> tuple[float | None, float | None]:
        """หา swing high/low ล่าสุด (fractal: จุดสูง/ต่ำกว่าเพื่อนบ้าน left/right แท่ง) ใน swing_lookback
        แท่งท้ายสุด — คืน (swing_high, swing_low) ล่าสุดที่เจอ หรือ None ถ้าไม่มี (ข้อมูลไม่พอ)
        """
        recent = window.iloc[-self.swing_lookback :]
        h, l = recent["high"].values, recent["low"].values
        n = len(recent)
        swing_high = swing_low = None
        for i in range(n - self.swing_right - 1, self.swing_left - 1, -1):
            window_h = h[i - self.swing_left : i + self.swing_right + 1]
            window_l = l[i - self.swing_left : i + self.swing_right + 1]
            if swing_high is None and h[i] == window_h.max():
                swing_high = float(h[i])
            if swing_low is None and l[i] == window_l.min():
                swing_low = float(l[i])
            if swing_high is not None and swing_low is not None:
                break
        return swing_high, swing_low

    def evaluate(self, data: MarketData, idx: int) -> Signal:
        lookback = self.min_lookback()
        if idx < lookback:
            return Signal.flat("ข้อมูลไม่พอ (warmup)")

        window = data.window(idx, lookback)
        close = window["close"]
        last_close = float(close.iloc[-1])

        # F3: BB width squeeze — เช็คก่อนสุด เพราะบล็อกทุกอย่างไม่ว่า F1/F2 จะว่ายังไง
        sma = close.rolling(self.bb_period).mean()
        std = close.rolling(self.bb_period).std()
        upper = sma + self.bb_std * std
        lower = sma - self.bb_std * std
        width = (upper - lower) / sma
        width_recent = width.iloc[-self.width_lookback :]
        width_now = float(width.iloc[-1])
        width_pct = float((width_recent < width_now).mean() * 100)
        squeeze = width_pct < self.squeeze_percentile

        ribbon_now, ribbon_prev = self._ribbon_series_last2(close)
        is_new_ribbon_signal = ribbon_now != 0 and ribbon_now != ribbon_prev

        direction: Direction | None = None
        setup_kind = ""
        if ribbon_now != 0:
            if is_new_ribbon_signal:
                direction = Direction.BUY if ribbon_now == 1 else Direction.SELL
                setup_kind = "ribbon flip"
            else:
                return Signal.flat("ribbon มีทิศแต่ไม่ใช่แท่งแรกของสัญญาณ (ค้างสถานะเดิม)")
        else:
            # F2: ribbon พันกัน (0) — เดินตาม BB แทน
            upper_now, lower_now = float(upper.iloc[-1]), float(lower.iloc[-1])
            if last_close > upper_now:
                direction = Direction.BUY
                setup_kind = "walking upper band"
            elif last_close < lower_now:
                direction = Direction.SELL
                setup_kind = "walking lower band"
            else:
                return Signal.flat("ribbon พันกัน + ราคาอยู่ในกรอบ BB (จุดที่บอทเดิมเสียเงินหนักสุด)")

        atr = self.atr(window, self.atr_period)
        if atr <= 0:
            return Signal.flat("ATR ไม่ถูกต้อง")

        swing_high, swing_low = self._swing_extremes(window)
        if swing_high is None or swing_low is None:
            return Signal.flat("หา swing structure ไม่เจอในช่วงที่กำหนด")

        if direction == Direction.BUY:
            sl = swing_low - atr * self.sl_buffer_atr
            tp = swing_high
            if sl >= last_close or tp <= last_close:
                return Signal.flat("swing SL/TP ผิดฝั่งราคาปัจจุบัน")
        else:
            sl = swing_high + atr * self.sl_buffer_atr
            tp = swing_low
            if sl <= last_close or tp >= last_close:
                return Signal.flat("swing SL/TP ผิดฝั่งราคาปัจจุบัน")

        # TP ที่ swing ถัดไปตรงตัวอักษรของสเปกมักใกล้เกินไป (swing สวนทางล่าสุดบน M30 บ่อยครั้งอยู่ใกล้
        # กว่าระยะ SL เอง) — ทดสอบแล้วทำให้ partial TP โดนก่อนที่ trailing runner จะมีโอกาสทำงาน
        # (ธรรมชาติของ Option B ที่สเปกเลือกคือ "ปิดจริงครึ่งนึงที่ TP ที่มีความหมาย" ต้องมีระยะคุ้มก่อน)
        # จึงยืดเป้าต่ำสุดเป็น min_target_rr เท่าของระยะ SL ถ้า swing ใกล้กว่านั้น — ไม่ทิ้ง swing target
        # (ยังใช้เมื่อไกลพอ) แค่กันไม่ให้ TP เล็กจนไร้ความหมาย
        risk_dist = abs(last_close - sl)
        reward_dist = abs(tp - last_close)
        if reward_dist < risk_dist * self.min_target_rr:
            tp = last_close + direction.sign * risk_dist * self.min_target_rr

        ctx = self.build_ctx(
            window=window,
            bar_time=window.index[-1],
            direction=direction,
            entry=last_close,
            sl=sl,
            tp=tp,
            atr=atr,
            setup_comment=(
                f"F1 ribbon={ribbon_now} F2={setup_kind} F3 width_pct={width_pct:.0f} "
                f"(squeeze={'ใช่' if squeeze else 'ไม่'}) SL จาก swing {sl:.2f} TP swing เป้าหมาย {tp:.2f} "
                f"เสนอ {direction.value}"
            ),
            squeeze=squeeze,
            width_pct=width_pct,
            is_new_ribbon_signal=is_new_ribbon_signal if ribbon_now != 0 else True,
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
            reason=f"MIDAS: {setup_kind} (F1={ribbon_now}, F3 width_pct={width_pct:.0f})",
            meta={"discussion": opinions},
        )

"""ทีม 11 "Fib Confluence Desk" — Fibonacci เป็นโซนปฏิกิริยา ไม่ใช่สัญญาณเข้าไม้เดี่ยวๆ

หลักปรัชญา (ตามที่โต๊ะเทรดสถาบันใช้ ไม่ใช่ retail "แตะเส้นแล้วเข้า"):
1. โครงสร้างตลาดต้องหนุนทิศทางก่อน (HH/HL หรือ LH/LL — ไม่เทรดตอน sideway)
2. ราคาต้องเข้าโซน fib retracement (ไม่ใช่ราคาเป๊ะ — โซนกว้าง ±ATR)
3. ต้องมี confluence หลายตัวเห็นตรงกัน (EMA/ADX/RSI/volume/session/multi-scale) รวมเป็น Confidence Score
4. ต้องรอแท่งยืนยัน price action (engulfing/pin bar) ภายใน N แท่ง ห้ามเข้าทันทีที่แตะเส้น
5. Confidence Score ต้องเกินเกณฑ์ที่ตั้งไว้ถึงจะเข้าไม้จริง

ขอบเขตที่ตัดออกอย่างตั้งใจ (ดูเหตุผลเต็มใน core/fib_engine.py docstring):
Order Block/FVG/Liquidity Sweep/BOS แบบเต็มรูป, multi-timeframe จริงข้าม TF, news filter อัตโนมัติ
"""
from __future__ import annotations

from core.committee import (
    Committee,
    CommitteeMember,
    make_proposer,
    make_risk_officer,
    make_session_analyst,
    make_volatility_analyst,
)
from core.fib_engine import (
    active_leg,
    classify_trend,
    detect_swings,
    fib_extension_levels,
    fib_retracement_levels,
    fib_zone_hit,
    price_action_confirmation,
)
from core.signal import Direction, MarketData, Signal
from core.strategy import Strategy, register_strategy


def _make_confidence_officer(name: str, threshold: float) -> CommitteeMember:
    def check(ctx: dict) -> tuple[bool, str]:
        score = ctx.get("confidence", 0.0)
        if score < threshold:
            return False, f"Confidence {score:.0f} ต่ำกว่าเกณฑ์ {threshold:.0f} ค้าน"
        return True, f"Confidence {score:.0f} ≥ เกณฑ์ {threshold:.0f} ({ctx.get('confluences', '')})"

    return CommitteeMember(name, "Confidence Officer", check)


@register_strategy
class FibonacciConfluenceStrategy(Strategy):
    name = "fib_confluence"
    description = (
        "Fibonacci confluence engine (สไตล์โต๊ะสถาบัน ไม่ใช่ retail): หาโครงสร้าง HH/HL หรือ "
        "LH/LL ก่อน (ไม่เทรด sideway) วาด fib retracement จากขาล่าสุด รอราคาเข้าโซน (±ATR ไม่ใช่ "
        "ราคาเป๊ะ) รอแท่งยืนยัน price action แล้วรวมคะแนนความมั่นใจจาก EMA/ADX/RSI/volume/session/"
        "multi-scale confluence — เข้าเมื่อคะแนนเกินเกณฑ์เท่านั้น TP อิง fib extension "
        "(127.2%/161.8%) ปิดบางส่วนที่ TP1 แล้ว trail ส่วนที่เหลือ SL อิงโครงสร้าง (หลัง swing) "
        "ไม่วางทับเส้น fib"
    )

    def __init__(
        self,
        swing_order: int = 3,
        higher_scale_order: int = 8,
        ema_fast: int = 50,
        ema_slow: int = 200,
        rsi_period: int = 14,
        adx_threshold: float = 20.0,
        zone_atr_mult: float = 0.25,
        atr_period: int = 14,
        confidence_threshold: float = 75.0,
        confirm_max_bars: int = 3,
        sl_mode: str = "structure",  # structure | atr
        atr_mult_sl: float = 1.5,
        sl_buffer_atr: float = 0.15,
        volume_lookback: int = 20,
    ):
        self.swing_order = swing_order
        self.higher_scale_order = higher_scale_order
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.rsi_period = rsi_period
        self.adx_threshold = adx_threshold
        self.zone_atr_mult = zone_atr_mult
        self.atr_period = atr_period
        self.confidence_threshold = confidence_threshold
        self.confirm_max_bars = confirm_max_bars
        self.sl_mode = sl_mode
        self.atr_mult_sl = atr_mult_sl
        self.sl_buffer_atr = sl_buffer_atr
        self.volume_lookback = volume_lookback
        self._committee = Committee(
            [
                make_proposer("นักวาดไฟโบ"),
                _make_confidence_officer("หัวหน้าคอนฟลูเอนซ์", confidence_threshold),
                make_risk_officer("หมวดเสี่ยงไฟโบ", min_rr=1.3),
                make_session_analyst("ปู่โมงไฟโบ"),
                make_volatility_analyst("นางพยากรณ์ ATR", max_spike_ratio=2.5),
            ]
        )

    def min_lookback(self) -> int:
        return self.ema_slow + self.higher_scale_order * 4 + 40

    def evaluate(self, data: MarketData, idx: int) -> Signal:
        lookback = self.min_lookback()
        if idx < lookback:
            return Signal.flat("ข้อมูลไม่พอ (warmup)")

        window = data.window(idx, lookback)
        close, high, low, volume = window["close"], window["high"], window["low"], window["volume"]

        atr = self.atr(window, self.atr_period)
        if atr <= 0:
            return Signal.flat("ATR ไม่ถูกต้อง")

        swings = detect_swings(window, order=self.swing_order)
        trend = classify_trend(swings)
        if trend == "sideway":
            return Signal.flat("โครงสร้างตลาดยัง sideway ไม่ใช้ Fibonacci")

        leg = active_leg(swings, trend)
        if leg is None:
            return Signal.flat("หาแกน swing ล่าสุดไม่ได้")
        anchor_low, anchor_high = leg
        fib_range = anchor_high.price - anchor_low.price
        if fib_range <= 0:
            return Signal.flat("ช่วง swing ผิดปกติ")

        direction = Direction.BUY if trend == "up" else Direction.SELL
        ret_levels = fib_retracement_levels(anchor_low.price, anchor_high.price, trend)
        zone_width = self.zone_atr_mult * atr
        last_close = float(close.iloc[-1])

        hit = fib_zone_hit(last_close, ret_levels, zone_width)
        if hit is None:
            return Signal.flat("ราคายังไม่เข้าโซน Fibonacci retracement")
        ratio, level_price = hit

        confirmed, pattern, bars_ago = price_action_confirmation(
            window, direction.sign, level_price - zone_width, level_price + zone_width,
            self.confirm_max_bars,
        )
        if not confirmed:
            return Signal.flat(
                f"เข้าโซน fib {ratio*100:.1f}% แล้วแต่ยังไม่มีแท่งยืนยัน price action ภายใน "
                f"{self.confirm_max_bars} แท่ง"
            )

        # --- Confluence scoring ---
        ema_f = close.ewm(span=self.ema_fast, adjust=False).mean().iloc[-1]
        ema_s = close.ewm(span=self.ema_slow, adjust=False).mean().iloc[-1]
        ema_aligned = (ema_f > ema_s) == (direction == Direction.BUY)

        rsi_val = float(self.rsi(close, self.rsi_period).iloc[-1])
        rsi_confirms = (rsi_val > 50) if direction == Direction.BUY else (rsi_val < 50)

        vol_avg = float(volume.tail(self.volume_lookback).mean())
        vol_now = float(volume.iloc[-1])
        volume_confirms = vol_avg > 0 and vol_now >= vol_avg

        # higher-scale confluence: proxy ของ "multi-timeframe/cluster" ด้วย swing order กว้างกว่า
        # บน TF เดียวกัน (ไม่ใช่ TF จริงที่สูงกว่า — ดู docstring core/fib_engine.py)
        higher_swings = detect_swings(window, order=self.higher_scale_order)
        higher_trend = classify_trend(higher_swings)
        higher_scale_agrees = higher_trend == trend

        from backtest.regime import compute_adx

        adx = float(compute_adx(window).iloc[-1])
        adx_confirms = adx >= self.adx_threshold

        session_hour = window.index[-1].hour
        session_confirms = 6 <= session_hour <= 20  # London+NY overlap โดยประมาณ (เวลาโบรก)

        fib_weight = {0.236: 5, 0.382: 12, 0.5: 15, 0.618: 20, 0.786: 10}.get(ratio, 0)
        confluences = []
        score = fib_weight
        confluences.append(f"fib{ratio*100:.1f}%+{fib_weight}")
        if ema_aligned:
            score += 15
            confluences.append("EMA+15")
        if adx_confirms:
            score += 15
            confluences.append("ADX+15")
        if rsi_confirms:
            score += 10
            confluences.append("RSI+10")
        if volume_confirms:
            score += 8
            confluences.append("Vol+8")
        if session_confirms:
            score += 7
            confluences.append("Session+7")
        if higher_scale_agrees:
            score += 10
            confluences.append("HigherScale+10")
        score += 10  # price action confirmation (เงื่อนไขบังคับอยู่แล้ว แต่ให้คะแนนด้วยตาม spec step6
        confluences.append(f"{pattern}+10")

        if score < self.confidence_threshold:
            return Signal.flat(
                f"Confidence {score:.0f} ต่ำกว่าเกณฑ์ {self.confidence_threshold:.0f} "
                f"({', '.join(confluences)})"
            )

        entry = last_close
        if self.sl_mode == "structure":
            if direction == Direction.BUY:
                sl = anchor_low.price - self.sl_buffer_atr * atr
            else:
                sl = anchor_high.price + self.sl_buffer_atr * atr
        else:
            sl = entry - direction.sign * (atr * self.atr_mult_sl)

        risk = abs(entry - sl)
        if risk <= 0:
            return Signal.flat("SL ผิดปกติ (ระยะเป็นศูนย์)")

        ext = fib_extension_levels(anchor_low.price, anchor_high.price, trend)
        tp = ext[1.618]  # engine ใช้เป็นเป้าหลัก (TP2) — TP1(1.272) ใช้ปิดบางส่วนผ่าน trade_management

        ctx = self.build_ctx(
            window=window,
            bar_time=window.index[-1],
            direction=direction,
            entry=entry,
            sl=sl,
            tp=tp,
            atr=atr,
            setup_comment=(
                f"โครงสร้าง{'ขึ้น' if trend=='up' else 'ลง'} (HH/HL หรือ LH/LL) วาด fib จาก "
                f"{anchor_low.price:.2f}->{anchor_high.price:.2f} ราคาเข้าโซน {ratio*100:.1f}% "
                f"({level_price:.2f}) ยืนยันด้วย {pattern} เสนอ {direction.value} "
                f"confidence={score:.0f}"
            ),
            confidence=score,
            confluences=", ".join(confluences),
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
            reason=f"Fib {ratio*100:.1f}% zone + {pattern}, confidence={score:.0f}",
            meta={"discussion": opinions},
        )

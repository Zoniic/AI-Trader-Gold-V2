"""ทีม "สายซิ่ง" — momentum scalping สำหรับ timeframe สั้น (M15/M5) เข้าไว ออกไว

ต่างจากทีมอื่นที่เน้นถือยาว/snowball: ทีมนี้ล่าโมเมนตัมระยะสั้นด้วย EMA เร็วสุดขั้ว (5/13) +
RSI ยืนยันแรงส่ง SL/TP แคบกว่าทีมอื่นมาก (R:R ~1:1.3) เพราะเป้าคือความถี่สูง ไม่ใช่ R ใหญ่ต่อไม้
คณะกรรมการเข้มเรื่อง volatility (กันเข้าไม้ตอนสเปรดกว้างกินเป้าหมายเล็กๆ หมด) และ session
(เลี่ยงช่วงตลาดบางที่สเปรดกว้างกว่าปกติ scalp เป้าเล็กไม่คุ้ม)
"""
from __future__ import annotations

from core.committee import (
    Committee,
    make_bias_analyst,
    make_proposer,
    make_risk_officer,
    make_session_analyst,
    make_volatility_analyst,
)
from core.signal import Direction, MarketData, Signal
from core.strategy import Strategy, register_strategy


@register_strategy
class MomentumScalperStrategy(Strategy):
    name = "momentum_scalper"
    description = (
        "สายซิ่ง — scalping ด้วย EMA เร็วสุดขั้ว (fast/slow ค่าเริ่มต้น 5/13) ยืนยันด้วย RSI "
        "momentum: เข้า BUY เมื่อ EMA ตัดขึ้น + RSI > 50 กำลังขึ้น, เข้า SELL เมื่อตัดลง + RSI < 50 "
        "กำลังลง SL/TP แคบ (ATR คูณ atr_mult_sl/atr_mult_tp ค่าเริ่มต้น 0.7/1.0 — R:R ~1:1.4) "
        "ออกแบบสำหรับ M15/M5 เน้นความถี่สูง ไม่ใช่ R ใหญ่ต่อไม้ คณะกรรมการกรองช่วง volatility "
        "สูงเกิน/session เงียบที่สเปรดกินเป้าหมายเล็กๆ ออก"
    )

    def __init__(
        self,
        fast: int = 5,
        slow: int = 13,
        structure_period: int = 50,
        rsi_period: int = 7,
        atr_period: int = 10,
        atr_mult_sl: float = 0.7,
        atr_mult_tp: float = 1.0,
    ):
        self.fast = fast
        self.slow = slow
        self.structure_period = structure_period
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.atr_mult_sl = atr_mult_sl
        self.atr_mult_tp = atr_mult_tp
        self._committee = Committee(
            [
                make_proposer("ไทฟูน"),
                # scalp เป้าเล็ก — volatility สูงเกินทำให้สเปรด/slippage กินเป้าหมด ต้องเข้มกว่าทีมถือยาว
                make_volatility_analyst("เจ๊วอล", max_spike_ratio=1.8),
                make_risk_officer("คุณเข้ม", min_rr=1.2),
                make_session_analyst("น้องไทม์"),
                # แม้ scalp ก็ยังไม่อยากสวน bias โครงสร้างใหญ่ (EMA ช้าสุด) — ลดโอกาสโดนเทรนด์ใหญ่กวาด
                make_bias_analyst("พี่สตรัค"),
            ]
        )

    def min_lookback(self) -> int:
        return max(self.slow, self.structure_period) + max(self.rsi_period, self.atr_period) + 5

    def evaluate(self, data: MarketData, idx: int) -> Signal:
        lookback = self.min_lookback()
        if idx < lookback:
            return Signal.flat("ข้อมูลไม่พอ (warmup)")

        window = data.window(idx, lookback)
        ema_fast = window["close"].ewm(span=self.fast, adjust=False).mean()
        ema_slow = window["close"].ewm(span=self.slow, adjust=False).mean()

        prev_diff = ema_fast.iloc[-2] - ema_slow.iloc[-2]
        curr_diff = ema_fast.iloc[-1] - ema_slow.iloc[-1]
        crossed_up = prev_diff <= 0 and curr_diff > 0
        crossed_down = prev_diff >= 0 and curr_diff < 0
        if not (crossed_up or crossed_down):
            return Signal.flat("ไม่มี crossover")

        rsi = self.rsi(window["close"], self.rsi_period)
        rsi_now, rsi_prev = rsi.iloc[-1], rsi.iloc[-2]
        # ยืนยันโมเมนตัม: RSI ต้องอยู่ฝั่งเดียวกับทิศทาง crossover และกำลังขยับไปทางนั้น (ไม่ใช่แค่ผ่านเส้น 50)
        if crossed_up and not (rsi_now > 50 and rsi_now > rsi_prev):
            return Signal.flat("RSI ไม่ยืนยันโมเมนตัมขาขึ้น")
        if crossed_down and not (rsi_now < 50 and rsi_now < rsi_prev):
            return Signal.flat("RSI ไม่ยืนยันโมเมนตัมขาลง")

        atr = self.atr(window, self.atr_period)
        if atr <= 0:
            return Signal.flat("ATR ไม่ถูกต้อง")

        entry = float(window["close"].iloc[-1])
        direction = Direction.BUY if crossed_up else Direction.SELL
        sl = entry - direction.sign * (atr * self.atr_mult_sl)
        tp = entry + direction.sign * (atr * self.atr_mult_tp)

        # bias โครงสร้างใหญ่ (EMA ช้ากว่า fast/slow ของ scalp เอง) — กันไม่ให้ scalp สวนเทรนด์ใหญ่
        ema_structure = window["close"].ewm(span=self.structure_period, adjust=False).mean().iloc[-1]
        price_vs_structure = entry - float(ema_structure)
        structure_noise_band = atr * 0.3  # ใกล้เส้นมากถือว่ากลาง ไม่นับเป็น bias ชัดเจน
        ema_bias = 0
        if abs(price_vs_structure) > structure_noise_band:
            ema_bias = 1 if price_vs_structure > 0 else -1

        ctx = self.build_ctx(
            window=window,
            bar_time=window.index[-1],
            direction=direction,
            entry=entry,
            sl=sl,
            tp=tp,
            atr=atr,
            ema_bias=ema_bias,
            setup_comment=(
                f"EMA{self.fast}/{self.slow} ตัด{'ขึ้น' if crossed_up else 'ลง'} "
                f"+ RSI{self.rsi_period}={rsi_now:.0f} ยืนยันโมเมนตัม เสนอ {direction.value} scalp"
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
            reason=f"scalp: EMA{self.fast}/{self.slow} + RSI{self.rsi_period} momentum",
            meta={"discussion": opinions},
        )

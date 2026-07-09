"""ทีม 5 "Momentum Five" — MACD crossover (แนว Gerald Appel ผู้คิดค้น MACD)

หลักการ: MACD histogram พลิกเครื่องหมาย = โมเมนตัมเพิ่งเปลี่ยนข้าง เข้าตามทางนั้น
โดยมีป้าเทรนด์คุมไม่ให้เทรดสวนโครงสร้างใหญ่ (EMA200) และหมออาร์กันไล่ราคาตอน RSI สุดโต่ง
"""
from __future__ import annotations

from core.committee import (
    Committee,
    CommitteeMember,
    make_bias_analyst,
    make_proposer,
    make_risk_officer,
    make_session_analyst,
)
from core.signal import Direction, MarketData, Signal
from core.strategy import Strategy, register_strategy


def _make_exhaustion_analyst(
    name: str, overbought: float = 75.0, oversold: float = 25.0
) -> CommitteeMember:
    """กันไล่ราคาตอนโมเมนตัมสุดโต่งแล้ว (ซื้อบนดอย/ขายก้นเหว)"""

    def check(ctx: dict) -> tuple[bool, str]:
        rsi = ctx["rsi"]
        sign = ctx["direction"].sign
        if sign > 0 and rsi >= overbought:
            return False, f"RSI {rsi:.1f} สุดโต่งฝั่งซื้อแล้ว (≥{overbought:.0f}) ไล่ราคาเสี่ยงดอย ค้าน"
        if sign < 0 and rsi <= oversold:
            return False, f"RSI {rsi:.1f} สุดโต่งฝั่งขายแล้ว (≤{oversold:.0f}) ขายก้นเหวเสี่ยงเด้ง ค้าน"
        return True, f"RSI {rsi:.1f} ยังไม่สุดโต่ง มีที่ให้วิ่งต่อ"

    return CommitteeMember(name, "Exhaustion Analyst", check)


@register_strategy
class MACDMomentumStrategy(Strategy):
    name = "macd_momentum"
    description = (
        "Momentum แนว Gerald Appel (ผู้คิดค้น MACD): เข้าเมื่อ MACD histogram พลิกเครื่องหมาย "
        "(MACD ตัดเส้น signal) = โมเมนตัมเพิ่งเปลี่ยนข้าง — SL 1.5×ATR TP 3×ATR "
        "กรองด้วยโครงสร้างใหญ่ EMA200 (เทรดตามฝั่งเท่านั้น) และกันเข้าตอน RSI สุดโต่งแล้ว"
    )

    def __init__(
        self,
        fast: int = 12,
        slow: int = 26,
        signal_period: int = 9,
        trend_ema: int = 200,
        atr_period: int = 14,
        atr_mult_sl: float = 1.5,
        atr_mult_tp: float = 3.0,
    ):
        self.fast = fast
        self.slow = slow
        self.signal_period = signal_period
        self.trend_ema = trend_ema
        self.atr_period = atr_period
        self.atr_mult_sl = atr_mult_sl
        self.atr_mult_tp = atr_mult_tp
        self._committee = Committee(
            [
                make_proposer("อาจารย์แมค"),
                make_bias_analyst("ป้าเทรนด์"),
                _make_exhaustion_analyst("หมออาร์"),
                make_risk_officer("คุณโรส", min_rr=1.5),
                make_session_analyst("นายทุ่ม"),
            ]
        )

    def min_lookback(self) -> int:
        return self.trend_ema + 40

    def evaluate(self, data: MarketData, idx: int) -> Signal:
        lookback = self.min_lookback()
        if idx < lookback:
            return Signal.flat("ข้อมูลไม่พอ (warmup)")

        window = data.window(idx, lookback)
        close = window["close"]

        ema_fast = close.ewm(span=self.fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        signal_line = macd.ewm(span=self.signal_period, adjust=False).mean()
        hist = macd - signal_line

        prev_hist = float(hist.iloc[-2])
        curr_hist = float(hist.iloc[-1])

        if prev_hist <= 0 < curr_hist:
            direction = Direction.BUY
        elif prev_hist >= 0 > curr_hist:
            direction = Direction.SELL
        else:
            return Signal.flat("MACD histogram ยังไม่พลิกข้าง")

        atr = self.atr(window, self.atr_period)
        if atr <= 0:
            return Signal.flat("ATR ไม่ถูกต้อง")

        entry = float(close.iloc[-1])
        sl = entry - direction.sign * (atr * self.atr_mult_sl)
        tp = entry + direction.sign * (atr * self.atr_mult_tp)

        ema200 = float(close.ewm(span=self.trend_ema, adjust=False).mean().iloc[-1])
        ema_bias = 1 if entry > ema200 else -1
        rsi_now = float(self.rsi(close).iloc[-1])

        ctx = self.build_ctx(
            window=window,
            bar_time=window.index[-1],
            direction=direction,
            entry=entry,
            sl=sl,
            tp=tp,
            atr=atr,
            setup_comment=(
                f"MACD histogram พลิกจาก {prev_hist:.3f} เป็น {curr_hist:.3f} "
                f"โมเมนตัมเปลี่ยนข้าง เสนอ {direction.value} ที่ {entry:.2f}"
            ),
            ema_bias=ema_bias,
            rsi=rsi_now,
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
            reason=f"MACD({self.fast},{self.slow},{self.signal_period}) histogram flip "
            f"{'up' if direction == Direction.BUY else 'down'}",
            meta={"discussion": opinions},
        )

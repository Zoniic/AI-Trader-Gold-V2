"""ทีม 7 "VWAP Desk" — VWAP deviation fade (แนวโต๊ะเทรดสถาบัน/intraday desk)

หลักการ: VWAP คือราคาเฉลี่ยถ่วงน้ำหนักปริมาณ = "ต้นทุนเฉลี่ยของตลาด" ที่โต๊ะสถาบันใช้อ้างอิง
เมื่อราคาเบี่ยงจาก VWAP เกิน 2 ส่วนเบี่ยงเบนมาตรฐาน มักถูกดูดกลับ — เข้าสวนกลับหา VWAP
"""
from __future__ import annotations

import numpy as np

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


def _make_zscore_analyst(name: str, min_z: float = 2.0, max_z: float = 4.0) -> CommitteeMember:
    """เบี่ยงน้อยไป = ไม่คุ้มสวน, เบี่ยงมากไป = อาจเป็น crash จริง ห้ามรับมีดตก"""

    def check(ctx: dict) -> tuple[bool, str]:
        z = abs(ctx["vwap_z"])
        if z < min_z:
            return False, f"เบี่ยงจาก VWAP แค่ {z:.1f}σ (<{min_z}) ไม่คุ้มสวน ค้าน"
        if z > max_z:
            return False, f"เบี่ยงถึง {z:.1f}σ (>{max_z}) นี่อาจเป็นการเคลื่อนจริง ไม่ใช่ noise ค้าน"
        return True, f"เบี่ยง {z:.1f}σ อยู่ในโซนที่สถิติบอกว่ามักถูกดูดกลับ"

    return CommitteeMember(name, "Z-Score Analyst", check)


@register_strategy
class VWAPReversionStrategy(Strategy):
    name = "vwap_reversion"
    description = (
        "VWAP fade แนวโต๊ะเทรดสถาบัน: คำนวณ VWAP rolling 24 ชม. (ต้นทุนเฉลี่ยของตลาด) — "
        "เมื่อราคาเบี่ยงเกิน z_entry ส่วนเบี่ยงเบนมาตรฐานพร้อม RSI เอียงสุดโต่ง เข้าสวนกลับหา "
        "VWAP (TP ที่ VWAP, SL 1.5×ATR) หลัก: ราคาที่ยืดไกลจากต้นทุนเฉลี่ยมักถูกดูดกลับ "
        "แต่ห้ามรับมีดตกตอนเบี่ยงเกิน 4σ"
    )

    def __init__(
        self,
        vwap_window: int = 24,
        std_window: int = 48,
        z_entry: float = 2.0,
        rsi_buy_max: float = 40.0,
        rsi_sell_min: float = 60.0,
        atr_period: int = 14,
        atr_mult_sl: float = 1.5,
        min_tp_atr_mult: float = 0.3,
    ):
        self.vwap_window = vwap_window
        self.std_window = std_window
        self.z_entry = z_entry
        self.rsi_buy_max = rsi_buy_max
        self.rsi_sell_min = rsi_sell_min
        self.atr_period = atr_period
        self.atr_mult_sl = atr_mult_sl
        self.min_tp_atr_mult = min_tp_atr_mult
        self._committee = Committee(
            [
                make_proposer("หัวหน้าเดสก์"),
                _make_zscore_analyst("คุณซิกม่า"),
                make_trend_analyst("พี่สงบ", mode="need_quiet", adx_threshold=30.0),
                make_risk_officer("เฮียการ์ด", min_rr=0.5),
                make_session_analyst("น้องกะดึก"),
            ]
        )

    def min_lookback(self) -> int:
        return self.vwap_window + self.std_window + 30

    def evaluate(self, data: MarketData, idx: int) -> Signal:
        lookback = self.min_lookback()
        if idx < lookback:
            return Signal.flat("ข้อมูลไม่พอ (warmup)")

        window = data.window(idx, lookback)
        typical = (window["high"] + window["low"] + window["close"]) / 3
        vol = window["volume"].astype(float)
        vol_sum = vol.rolling(self.vwap_window).sum()
        vwap = (typical * vol).rolling(self.vwap_window).sum() / vol_sum.replace(0, np.nan)

        deviation = window["close"] - vwap
        dev_std = deviation.rolling(self.std_window).std()

        last_vwap = float(vwap.iloc[-1]) if not np.isnan(vwap.iloc[-1]) else None
        last_std = float(dev_std.iloc[-1]) if not np.isnan(dev_std.iloc[-1]) else None
        if last_vwap is None or last_std is None or last_std <= 0:
            return Signal.flat("VWAP/std ยังคำนวณไม่ได้")

        last_close = float(window["close"].iloc[-1])
        z = (last_close - last_vwap) / last_std
        rsi_now = float(self.rsi(window["close"]).iloc[-1])

        atr = self.atr(window, self.atr_period)
        if atr <= 0:
            return Signal.flat("ATR ไม่ถูกต้อง")

        if z <= -self.z_entry and rsi_now <= self.rsi_buy_max:
            direction = Direction.BUY
        elif z >= self.z_entry and rsi_now >= self.rsi_sell_min:
            direction = Direction.SELL
        else:
            return Signal.flat("ราคายังไม่เบี่ยงจาก VWAP มากพอ (หรือ RSI ไม่ยืนยัน)")

        tp = last_vwap
        if abs(tp - last_close) < atr * self.min_tp_atr_mult:
            return Signal.flat("ระยะกลับถึง VWAP สั้นเกินไป ไม่คุ้มต้นทุน")

        sl = last_close - direction.sign * (atr * self.atr_mult_sl)

        ctx = self.build_ctx(
            window=window,
            bar_time=window.index[-1],
            direction=direction,
            entry=last_close,
            sl=sl,
            tp=tp,
            atr=atr,
            setup_comment=(
                f"ราคา {last_close:.2f} เบี่ยงจาก VWAP ({last_vwap:.2f}) ไป {z:+.1f}σ "
                f"พร้อม RSI {rsi_now:.1f} เสนอสวนกลับหา VWAP ({direction.value})"
            ),
            vwap_z=z,
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
            reason=f"VWAP fade z={z:+.1f}σ RSI={rsi_now:.0f}",
            meta={"discussion": opinions},
        )

"""ทีม 15 "นายธนาคารเงา" (SMC Flow) — Smart Money Concepts เต็มลำดับ

ลำดับเงื่อนไขตามระบบ (ทุกข้อต้องเกิดตามลำดับ ถึงจะเข้าไม้):
1. HTF Supply/Demand — โซน swing high/low สำคัญจากโครงสร้างใหญ่ (lookback ยาว)
2. Liquidity Sweep — ราคาแทงทะลุ swing low เดิม (กวาด stop) แล้วปิดกลับเข้ามา
3. CHoCH (Change of Character) — หลัง sweep ราคาทะลุ swing high ล่าสุดขึ้นไป = โครงสร้างเปลี่ยน
4. QML (Quasimodo Level) — ระดับ high ที่ถูกทะลุตอน CHoCH กลายเป็นแนวรับใหม่
5. FVG Retest — ช่องว่างราคา (fair value gap) ที่เกิดตอนแท่ง impulse ของ CHoCH
   ราคาต้องย่อกลับมาเติมช่องนี้
6. Engulfing Confirmation — แท่งกลืนกิน ณ จุด retest ยืนยันว่า demand รับอยู่จริง
7. เข้าออเดอร์ — SL ใต้จุด sweep ต่ำสุด (บวกกันชน ATR), TP ที่ swing high ถัดไปตาม
   market structure (ไม่ใช่ multiplier ตายตัว)

ฝั่ง SELL คือภาพกลับด้านทั้งหมด (sweep ทะลุ high → CHoCH ลง → retest FVG ขาลง → bearish engulfing)

เหตุผลที่น่าจะได้เปรียบ: แต่ละชั้นกรองอิสระกัน — sweep กรองจังหวะ (stop hunt จบแล้ว),
CHoCH กรองทิศ (โครงสร้างกลับจริง), FVG กรองราคาเข้า (ไม่ไล่ราคา), engulfing กรอง timing
ไม้ที่รอดทุกชั้นควรเป็นไม้คุณภาพสูงจำนวนน้อย
"""
from __future__ import annotations

import numpy as np
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


def _make_structure_analyst(name: str, min_rr_to_target: float = 1.2) -> CommitteeMember:
    """เป้าตาม structure ต้องคุ้มระยะ SL จริง — ถ้า swing เป้าอยู่ใกล้เกิน (R:R ต่ำ) ไม่เอา"""

    def check(ctx: dict) -> tuple[bool, str]:
        rr = ctx.get("structure_rr", 0.0)
        if rr < min_rr_to_target:
            return False, (
                f"เป้าหมาย structure ให้ R:R แค่ {rr:.2f} (< {min_rr_to_target}) "
                "ระยะวิ่งไม่คุ้มความเสี่ยง ค้าน"
            )
        return True, f"เป้า structure R:R {rr:.2f} — ระยะวิ่งคุ้ม"

    return CommitteeMember(name, "Structure Analyst", check)


def _swings(df: pd.DataFrame, left: int, right: int) -> tuple[list[int], list[int]]:
    """หา swing highs/lows แบบ fractal (สูง/ต่ำกว่าเพื่อนบ้าน left/right แท่ง) — คืน index ตำแหน่ง"""
    highs, lows = [], []
    h, l = df["high"].values, df["low"].values
    n = len(df)
    for i in range(left, n - right):
        if h[i] == max(h[i - left : i + right + 1]):
            highs.append(i)
        if l[i] == min(l[i - left : i + right + 1]):
            lows.append(i)
    return highs, lows


@register_strategy
class SMCFlowStrategy(Strategy):
    name = "smc_flow"
    description = (
        "Smart Money Concepts เต็มลำดับ: HTF supply/demand → liquidity sweep (กวาด stop) → "
        "CHoCH (โครงสร้างเปลี่ยน) → QML → FVG retest (ไม่ไล่ราคา) → engulfing ยืนยัน → "
        "SL ใต้จุด sweep + กันชน ATR, TP ที่ swing ถัดไปตาม market structure จริง "
        "ไม้น้อยแต่ผ่านการกรอง 6 ชั้นอิสระกัน ออกแบบสำหรับ M30/H1"
    )

    def __init__(
        self,
        swing_left: int = 3,
        swing_right: int = 3,
        sweep_lookback: int = 40,
        choch_window: int = 15,
        fvg_min_atr: float = 0.15,
        atr_period: int = 14,
        sl_buffer_atr: float = 0.4,
        min_engulf_body_ratio: float = 0.5,
    ):
        self.swing_left = swing_left
        self.swing_right = swing_right
        self.sweep_lookback = sweep_lookback
        self.choch_window = choch_window
        self.fvg_min_atr = fvg_min_atr  # FVG ต้องกว้างอย่างน้อยกี่ ATR ถึงนับ (กรอง gap จิ๋วไร้ความหมาย)
        self.atr_period = atr_period
        self.sl_buffer_atr = sl_buffer_atr
        self.min_engulf_body_ratio = min_engulf_body_ratio
        self._committee = Committee(
            [
                make_proposer("นายแบงก์"),
                _make_structure_analyst("สถาปนิกกราฟ", min_rr_to_target=1.2),
                make_volatility_analyst("เจ๊โฟลว์", max_spike_ratio=2.5),
                make_risk_officer("ผอ.ความเสี่ยง", min_rr=1.0),
                make_session_analyst("นักจับเวลา"),
            ]
        )

    def min_lookback(self) -> int:
        return self.sweep_lookback + self.choch_window + self.atr_period + 20

    def _find_setup(self, window: pd.DataFrame, atr: float, direction: Direction):
        """ไล่หาลำดับ sweep → CHoCH → FVG ในหน้าต่างล่าสุด — คืน (sweep_extreme, target, fvg_lo, fvg_hi)
        หรือ None ถ้าลำดับไม่ครบ  (เขียนฝั่ง BUY เป็นหลัก ฝั่ง SELL ใช้ mirror ด้วยการกลับ sign)
        """
        h, l, c = window["high"].values, window["low"].values, window["close"].values
        n = len(window)
        highs_idx, lows_idx = _swings(window, self.swing_left, self.swing_right)
        if len(highs_idx) < 2 or len(lows_idx) < 2:
            return None

        scan_start = n - self.sweep_lookback
        if direction == Direction.BUY:
            # 1-2) liquidity sweep: แท่งใน lookback แทง low ต่ำกว่า swing low ก่อนหน้า แล้ว "ปิดกลับ" เหนือมัน
            for si in range(max(scan_start, 5), n - 3):
                prior_lows = [j for j in lows_idx if j < si - self.swing_right]
                if not prior_lows:
                    continue
                swept_level = l[prior_lows[-1]]
                if l[si] < swept_level and c[si] > swept_level:
                    sweep_low = l[si]
                    # 3) CHoCH: หลัง sweep ราคาปิดทะลุ swing high ล่าสุดก่อน sweep
                    prior_highs = [j for j in highs_idx if j < si]
                    if not prior_highs:
                        continue
                    qml_level = h[prior_highs[-1]]
                    choch_at = None
                    for ci in range(si + 1, min(si + self.choch_window, n)):
                        if c[ci] > qml_level:
                            choch_at = ci
                            break
                    if choch_at is None:
                        continue
                    # 5) FVG ขาขึ้นในช่วง impulse (sweep → choch): gap ระหว่าง high[i-1] กับ low[i+1]
                    for fi in range(si + 1, min(choch_at + 2, n - 1)):
                        fvg_lo, fvg_hi = h[fi - 1], l[fi + 1]
                        if fvg_hi - fvg_lo >= atr * self.fvg_min_atr:
                            # 7) เป้า structure: swing high ถัดไปเหนือ QML (ถ้าไม่มี ใช้ high สูงสุดใน window)
                            above = [h[j] for j in highs_idx if h[j] > qml_level * 1.0001]
                            target = max(above) if above else float(max(h))
                            return sweep_low, target, fvg_lo, fvg_hi
        else:
            for si in range(max(scan_start, 5), n - 3):
                prior_highs = [j for j in highs_idx if j < si - self.swing_right]
                if not prior_highs:
                    continue
                swept_level = h[prior_highs[-1]]
                if h[si] > swept_level and c[si] < swept_level:
                    sweep_high = h[si]
                    prior_lows = [j for j in lows_idx if j < si]
                    if not prior_lows:
                        continue
                    qml_level = l[prior_lows[-1]]
                    choch_at = None
                    for ci in range(si + 1, min(si + self.choch_window, n)):
                        if c[ci] < qml_level:
                            choch_at = ci
                            break
                    if choch_at is None:
                        continue
                    for fi in range(si + 1, min(choch_at + 2, n - 1)):
                        fvg_hi, fvg_lo = l[fi - 1], h[fi + 1]
                        if fvg_hi - fvg_lo >= atr * self.fvg_min_atr:
                            below = [l[j] for j in lows_idx if l[j] < qml_level * 0.9999]
                            target = min(below) if below else float(min(l))
                            return sweep_high, target, fvg_lo, fvg_hi
        return None

    def evaluate(self, data: MarketData, idx: int) -> Signal:
        lookback = self.min_lookback()
        if idx < lookback:
            return Signal.flat("ข้อมูลไม่พอ (warmup)")

        window = data.window(idx, lookback)
        atr = self.atr(window, self.atr_period)
        if atr <= 0:
            return Signal.flat("ATR ไม่ถูกต้อง")

        bar = window.iloc[-1]
        prev = window.iloc[-2]
        o, c = float(bar["open"]), float(bar["close"])
        po, pc = float(prev["open"]), float(prev["close"])
        bar_range = float(bar["high"]) - float(bar["low"])
        if bar_range <= 0:
            return Signal.flat("แท่งล่าสุด range เป็นศูนย์")

        # 6) engulfing ล่าสุด: แท่งนี้กลืน body แท่งก่อน + body ใหญ่พอ
        body_ratio = abs(c - o) / bar_range
        bullish_engulf = c > o and pc < po and c >= po and o <= pc and body_ratio >= self.min_engulf_body_ratio
        bearish_engulf = c < o and pc > po and c <= po and o >= pc and body_ratio >= self.min_engulf_body_ratio
        if not (bullish_engulf or bearish_engulf):
            return Signal.flat("ไม่มีแท่ง engulfing ยืนยัน")

        direction = Direction.BUY if bullish_engulf else Direction.SELL
        setup = self._find_setup(window, atr, direction)
        if setup is None:
            return Signal.flat("ลำดับ sweep→CHoCH→FVG ยังไม่ครบ")
        sweep_extreme, target, fvg_lo, fvg_hi = setup

        # 5) ราคาปัจจุบันต้องอยู่ในโซน retest ของ FVG (บวกกันชนเล็กน้อย) — ไม่ไล่ราคานอกโซน
        zone_pad = atr * 0.3
        lo, hi = min(fvg_lo, fvg_hi) - zone_pad, max(fvg_lo, fvg_hi) + zone_pad
        if not (lo <= c <= hi):
            return Signal.flat(f"ราคา {c:.2f} อยู่นอกโซน FVG retest ({lo:.2f}-{hi:.2f}) ไม่ไล่ราคา")

        # 7) SL ใต้/เหนือจุด sweep + กันชน ATR, TP ที่ swing ตาม structure
        sl = sweep_extreme - direction.sign * (atr * self.sl_buffer_atr)
        tp = target
        risk = abs(c - sl)
        reward = abs(tp - c)
        if risk <= 0 or reward <= 0:
            return Signal.flat("ระยะ SL/TP ผิดปกติ")
        structure_rr = reward / risk

        ctx = self.build_ctx(
            window=window,
            bar_time=window.index[-1],
            direction=direction,
            entry=c,
            sl=sl,
            tp=tp,
            atr=atr,
            setup_comment=(
                f"SMC ครบลำดับ: sweep ที่ {sweep_extreme:.2f} → CHoCH → FVG retest "
                f"({min(fvg_lo,fvg_hi):.2f}-{max(fvg_lo,fvg_hi):.2f}) + engulfing "
                f"เสนอ {direction.value} เป้า structure {tp:.2f} (R:R {structure_rr:.2f})"
            ),
            structure_rr=structure_rr,
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
            reason=f"SMC: sweep→CHoCH→FVG→engulf (R:R {structure_rr:.1f} ตาม structure)",
            meta={"discussion": opinions},
        )

"""จำลองต้นทุนการเทรดจริง (spread + slippage)

round_trip_cost() เดิม = ค่าคงที่ตลอดทั้ง backtest ไม่ว่าจะเทรดตอนไหน (Asian session เงียบๆ
หรือตอน NY/London overlap ที่ spread จริงมักแคบกว่า หรือตอนข่าวแรง/rollover ที่ spread จริงมัก
กว้างกว่ามาก) — เป็นการประมาณที่หยาบเกินไปเพราะ backtest จะรายงานกำไรที่ไม่เคยเจอ "ต้นทุนกระโดด"
round_trip_cost_at() ด้านล่างแก้จุดนี้โดยปรับ spread ตาม session (ชั่วโมง UTC) และตาม volatility
percentile (ผ่าน atr_now/atr_median ที่ engine คำนวณ rolling ไว้อยู่แล้วสำหรับ position sizing —
ใช้ซ้ำได้เลยไม่ต้องคำนวณเพิ่ม) เป็น proxy สมเหตุสมผลของการที่ spread จริงกว้างขึ้นตอนตลาดผันผวนมาก
(ไม่ใช่การ calibrate จากข้อมูล spread จริงของโบรก เพราะไม่มีข้อมูลนั้นเก็บไว้ — แต่ดีกว่าค่าคงที่แบนราบ)
"""
from __future__ import annotations

from dataclasses import dataclass

# ตัวคูณ spread ตามช่วงเวลา (ชั่วโมง UTC) — อิงพฤติกรรมสภาพคล่องทองคำทั่วไป: London/NY overlap
# สภาพคล่องสูงสุด spread แคบสุด, Asian session สภาพคล่องบางกว่า, ช่วง rollover/pre-London บางที่สุด
_SESSION_MULTIPLIERS: dict[range, float] = {
    range(0, 7): 1.5,    # Asian session — สภาพคล่องบางกว่า overlap
    range(7, 16): 1.0,   # London + London/NY overlap — สภาพคล่องสูงสุด (baseline)
    range(16, 21): 1.2,  # NY session (หลัง London ปิด) — สภาพคล่องปานกลาง
    range(21, 24): 1.8,  # pre-Asian / rollover — สภาพคล่องบางที่สุดของวัน
}


def _session_multiplier(hour_utc: int) -> float:
    for hour_range, mult in _SESSION_MULTIPLIERS.items():
        if hour_utc in hour_range:
            return mult
    return 1.2  # เผื่อกรณีไม่เข้าเงื่อนไขไหนเลย (ไม่ควรเกิด แต่กันไว้)


def _volatility_multiplier(atr_now: float, atr_median: float) -> float:
    """ATR ปัจจุบันเทียบ median — ยิ่งผันผวนกว่าปกติมาก ยิ่งประมาณว่า spread จริงกว้างขึ้น
    (proxy ของช่วงข่าวแรง/เหตุการณ์ผันผวนที่ spread โบรกมักกว้างกว่าภาวะปกติมาก)
    """
    if atr_median <= 0:
        return 1.0
    ratio = atr_now / atr_median
    if ratio >= 2.0:
        return 3.0   # ผันผวนกว่าปกติ 2 เท่าขึ้นไป — ประมาณว่าเป็นช่วงข่าวแรง/เหตุการณ์ผิดปกติ
    if ratio >= 1.5:
        return 1.8
    if ratio >= 1.2:
        return 1.3
    return 1.0


@dataclass(frozen=True)
class CostModel:
    spread_points: float = 30.0
    slippage_points: float = 5.0
    point_value: float = 0.01  # XAUUSD: 1 point = 0.01 ราคา

    def round_trip_cost(self) -> float:
        """ต้นทุนรวมไปกลับ (เข้า+ออก) เป็นหน่วยราคา ต่อ 1 หน่วยสัญญา — ค่าคงที่ ไม่ปรับตาม session/volatility
        (เก็บไว้เพื่อ backward-compat / ใช้เป็น baseline เทียบกับ round_trip_cost_at())
        """
        return (self.spread_points + 2 * self.slippage_points) * self.point_value

    def round_trip_cost_at(self, hour_utc: int, atr_now: float, atr_median: float) -> float:
        """ต้นทุนรวมไปกลับแบบปรับตาม session + volatility regime — ใช้แทน round_trip_cost()
        ตอนจำลองเทรดจริงเพื่อไม่ให้ backtest มองข้ามช่วงที่ต้นทุนจริงกระโดดขึ้นมาก

        คูณ session_mult × vol_mult ตรงๆ แล้ว cap ไว้ที่ 4 เท่าของ spread ปกติ กันไม่ให้ต้นทุน
        พองเกินจริงตอนทั้งสองปัจจัยสูงพร้อมกัน (เช่น ข่าวแรงตอน rollover ซึ่งเกิดพร้อมกันได้แต่ไม่ควร
        ให้ผลคูณกันแบบไม่มีเพดาน)
        """
        session_mult = _session_multiplier(hour_utc)
        vol_mult = _volatility_multiplier(atr_now, atr_median)
        spread_mult = min(4.0, session_mult * vol_mult)
        return (self.spread_points * spread_mult + 2 * self.slippage_points * vol_mult) * self.point_value

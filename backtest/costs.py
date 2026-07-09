"""จำลองต้นทุนการเทรดจริง (spread + slippage) — ไม่มี regime แยกแบบ V1 เพื่อความเรียบง่าย"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    spread_points: float = 30.0
    slippage_points: float = 5.0
    point_value: float = 0.01  # XAUUSD: 1 point = 0.01 ราคา

    def round_trip_cost(self) -> float:
        """ต้นทุนรวมไปกลับ (เข้า+ออก) เป็นหน่วยราคา ต่อ 1 หน่วยสัญญา"""
        return (self.spread_points + 2 * self.slippage_points) * self.point_value

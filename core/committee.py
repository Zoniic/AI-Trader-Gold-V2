"""คณะนักเทรด 5 คนต่อทีม — โหวต + ให้ความเห็นก่อนเข้าไม้ทุกครั้ง

กติกา: ทุกทีมมีนักเทรด 5 คน (1 คนเสนอ setup + 4 คน review คนละด้าน) ต้องได้เสียง
อนุมัติ >= min_approvals (ค่าเริ่มต้น 4/5 คือยอมให้ค้านได้ 1 เสียง) ถึงจะเข้าไม้จริง
ทุกความเห็นคำนวณจากตัวเลขจริง ไม่ใช่ข้อความตายตัว และถูกบันทึกลง DB เพื่อดูย้อนหลังบนเว็บ
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# ctx ที่แต่ละกลยุทธ์ส่งเข้ามาให้กรรมการดู — คีย์มาตรฐาน:
#   bar_time, direction (Direction), entry, sl, tp, atr, atr_median, adx, setup_comment
# กลยุทธ์เพิ่มคีย์เฉพาะทีมได้ตามต้องการ (เช่น rsi, bandwidth, range_width)

CheckFn = Callable[[dict], tuple[bool, str]]


@dataclass
class CommitteeMember:
    name: str
    role: str
    check: CheckFn


class Committee:
    def __init__(self, members: list[CommitteeMember], min_approvals: int = 4):
        self.members = members
        self.min_approvals = min_approvals

    def review(self, ctx: dict) -> tuple[bool, list[dict]]:
        """คืน (อนุมัติไหม, ความเห็นทั้ง 5 คน) — ความเห็นเก็บเป็น dict พร้อม serialize ลง DB"""
        opinions: list[dict] = []
        approvals = 0
        for member in self.members:
            approve, comment = member.check(ctx)
            approvals += int(approve)
            opinions.append(
                {
                    "member": member.name,
                    "role": member.role,
                    "approve": bool(approve),
                    "comment": comment,
                }
            )
        return approvals >= self.min_approvals, opinions


# --- โรงงานสร้าง reviewer มาตรฐาน ใช้ซ้ำได้ทุกทีม (แต่ตั้ง threshold ต่างกันได้) ---


def make_proposer(name: str, role: str = "Setup Trader") -> CommitteeMember:
    """คนเสนอไม้ — เห็น setup ตามเงื่อนไขทีมแล้วถึงเรียกประชุม จึงอนุมัติเสมอพร้อมอธิบาย setup"""

    def check(ctx: dict) -> tuple[bool, str]:
        return True, ctx.get("setup_comment", "เห็น setup ครบเงื่อนไขทีม เสนอเข้าไม้")

    return CommitteeMember(name, role, check)


def make_risk_officer(name: str, min_rr: float = 1.0) -> CommitteeMember:
    """เช็คอัตราส่วนกำไรคาดหวังต่อความเสี่ยง (R:R) ต้องไม่ต่ำกว่าเกณฑ์ทีม"""

    def check(ctx: dict) -> tuple[bool, str]:
        entry, sl, tp = ctx["entry"], ctx["sl"], ctx["tp"]
        risk = abs(entry - sl)
        if risk <= 0:
            return False, "ระยะ SL เป็นศูนย์ ผิดปกติ ค้าน"
        rr = abs(tp - entry) / risk
        if rr < min_rr:
            return False, f"R:R {rr:.2f} ต่ำกว่าเกณฑ์ทีม {min_rr:.1f} ค้าน"
        return True, f"R:R {rr:.2f} ผ่านเกณฑ์ ≥{min_rr:.1f}"

    return CommitteeMember(name, "Risk Officer", check)


def make_session_analyst(
    name: str, blocked_hours: frozenset[int] = frozenset({23, 0})
) -> CommitteeMember:
    """เลี่ยงชั่วโมง rollover/สภาพคล่องต่ำ (เวลาโบรก GMT+2/+3: ราว 23:00-01:00 สเปรดถ่างมาก)"""

    def check(ctx: dict) -> tuple[bool, str]:
        hour = ctx["bar_time"].hour
        if hour in blocked_hours:
            return False, f"ชั่วโมง {hour:02d}:00 เป็นช่วง rollover สเปรดถ่าง ค้าน"
        return True, f"ชั่วโมง {hour:02d}:00 สภาพคล่องปกติ"

    return CommitteeMember(name, "Session Analyst", check)


def make_trend_analyst(
    name: str, mode: str = "need_trend", adx_threshold: float = 20.0
) -> CommitteeMember:
    """ดูความแรงเทรนด์ผ่าน ADX — ทีม trend-following ต้องการ ADX สูง, ทีม fade ต้องการ ADX ต่ำ"""

    def check(ctx: dict) -> tuple[bool, str]:
        adx = ctx["adx"]
        if mode == "need_trend":
            if adx >= adx_threshold:
                return True, f"ADX {adx:.1f} ≥ {adx_threshold:.0f} เทรนด์แรงพอ เหมาะกับท่าทีม"
            return False, f"ADX {adx:.1f} < {adx_threshold:.0f} เทรนด์อ่อน ท่าตามเทรนด์เสี่ยงหลอก ค้าน"
        # need_quiet: ท่าสวนเทรนด์/แกว่งกรอบ ต้องการตลาดไม่เป็นเทรนด์แรง
        if adx <= adx_threshold:
            return True, f"ADX {adx:.1f} ≤ {adx_threshold:.0f} ตลาดไม่เทรนด์แรง เหมาะกับท่าสวน"
        return False, f"ADX {adx:.1f} > {adx_threshold:.0f} เทรนด์แรง สวนตอนนี้อันตราย ค้าน"

    return CommitteeMember(name, "Trend Analyst", check)


def make_volatility_analyst(
    name: str, max_spike_ratio: float = 2.5
) -> CommitteeMember:
    """กันเข้าไม้ตอนความผันผวนพุ่งผิดปกติ (เช่นช่วงข่าวแรง) เทียบ ATR ปัจจุบันกับค่ากลางย้อนหลัง"""

    def check(ctx: dict) -> tuple[bool, str]:
        atr, atr_median = ctx["atr"], ctx["atr_median"]
        if atr_median <= 0:
            return False, "ATR median ผิดปกติ ค้าน"
        ratio = atr / atr_median
        if ratio > max_spike_ratio:
            return False, f"ATR พุ่ง {ratio:.1f} เท่าของค่าปกติ (>{max_spike_ratio:.1f}x) น่าจะมีข่าวแรง ค้าน"
        return True, f"ATR {ratio:.1f} เท่าของค่าปกติ อยู่ในโซนรับได้"

    return CommitteeMember(name, "Volatility Analyst", check)


def make_bias_analyst(name: str) -> CommitteeMember:
    """เช็คว่าทิศทางไม้ตรงกับ bias โครงสร้างใหญ่ (ctx["ema_bias"]: +1 ขึ้น / -1 ลง / 0 กลาง)"""

    def check(ctx: dict) -> tuple[bool, str]:
        bias = ctx.get("ema_bias", 0)
        direction_sign = ctx["direction"].sign
        if bias == 0:
            return True, "โครงสร้างใหญ่เป็นกลาง ไม่ขัดทิศทางไม้"
        if bias == direction_sign:
            return True, f"ทิศทางไม้ตรงกับ bias โครงสร้างใหญ่ ({'ขาขึ้น' if bias > 0 else 'ขาลง'})"
        return False, f"ไม้สวน bias โครงสร้างใหญ่ ({'ขาขึ้น' if bias > 0 else 'ขาลง'}) ค้าน"

    return CommitteeMember(name, "Structure Analyst", check)

"""คำนวณขนาดล็อต + ลำดับชั้นการคุมความเสี่ยง — ไม่ผูกกับ strategy/backtest ใช้เดี่ยวได้

ลำดับชั้น (ทุกทีมต้องมีครบ):
1. Risk ต่อไม้    — % ของทุน กำหนดต่อทีม (0.25/0.5/1.0 ตามความพิสูจน์แล้วของทีม)
2. Risk ต่อวัน    — ขาดทุนสะสมวันนี้ถึงลิมิต → พักถึงวันใหม่ (ไม่ใช่ตายถาวร)
3. Risk ต่อสัปดาห์ — เช่นเดียวกัน ระดับสัปดาห์
4. Max Drawdown  — ชนเพดาน → kill switch หยุดถาวร (คนต้องมาตัดสินใจเอง)

Position sizing มี 2 โหมด:
- fixed:      lot = ทุน×risk% / ระยะSL (มาตรฐาน — ปรับตาม SL อยู่แล้วจึง ATR-adaptive ในตัว)
- vol_scaled: เหมือน fixed แต่ลด risk% ลงตอนตลาดผันผวนกว่าปกติ / เพิ่มเล็กน้อยตอนเงียบ
              (risk_scale = ATR_median/ATR ปัจจุบัน จำกัดช่วง vol_scale_min..max)

DD-budget targeting (dd_targeting=True, ใช้ร่วมกับโหมดไหนก็ได้):
รู้ MaxDD เพดานอยู่แล้ว (max_drawdown_pct) — ใช้ "พื้นที่ว่าง" ก่อนชนเพดานมาปรับขนาดไม้แทนการ
คูณ lot ตรงๆ แบบเดิม (ซึ่งทดสอบแล้วว่าคูณ 2x ทำให้ DD พุ่งจาก 22%→40% ไม่เป็นสัดส่วนเชิงเส้น
และ 4x ทำให้บัญชีล้างเพราะ compounding ทบต้น drawdown เร็วกว่ากำไร):
- ห่างเพดานมาก (used <= 30% ของ budget) → boost แบบลดหลั่นจนถึง 1.0x ที่ used=30%
- ใกล้เพดานขึ้นเรื่อยๆ (used 30%→100%) → risk ลดเป็นเส้นตรงจนเหลือ dd_budget_floor
กัน "ยิ่งใกล้ตาย ยิ่งลงหนัก" (พฤติกรรม revenge/martingale) และให้ระบบเสี่ยงเพิ่มได้เฉพาะตอนมี
กันชนเยอะจริง — ยังต้อง cap boost ไว้ต่ำ (ดีฟอลต์ 1.3x) เพราะข้อมูลจริงแสดงว่า leverage ที่สูง
กว่านี้ทำให้ผลลัพธ์ไม่เป็นเชิงเส้นและเสี่ยงเกินคุ้ม
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskConfig:
    account_balance: float = 10000.0
    risk_per_trade_pct: float = 1.0
    max_drawdown_pct: float = 20.0
    max_daily_loss_pct: float | None = None  # None = ไม่จำกัดรายวัน
    max_weekly_loss_pct: float | None = None
    sizing_mode: str = "fixed"  # fixed | vol_scaled
    vol_scale_min: float = 0.5
    vol_scale_max: float = 1.5
    dd_targeting: bool = False  # ใช้พื้นที่ว่างก่อนชน max_drawdown_pct ปรับขนาดไม้ (ดู docstring บนไฟล์)
    dd_budget_headroom: float = 0.3  # สัดส่วนของ budget ที่ยังถือว่า "ปลอดภัย พอ boost ได้"
    dd_budget_boost_cap: float = 1.3  # risk_scale สูงสุดตอนห่างเพดานมาก (ต่ำไว้ตั้งใจ ดูdocstring)
    dd_budget_floor: float = 0.4  # risk_scale ต่ำสุดตอนใกล้ชนเพดาน (กันลงหนักตอนใกล้ตาย)
    # kill-switch mode: permanent = หยุดถาวรรอคนมาเปิด, auto_recover = เข้าโหมด probation อัตโนมัติ
    dd_halt_mode: str = "permanent"  # permanent | auto_recover
    dd_probation_scale: float = 0.35  # ตอน probation ลด risk เหลือกี่เท่า (เทรดเล็กเพื่อค่อยๆฟื้น)
    dd_resume_pct: float = 10.0  # DD ลดต่ำกว่านี้ = พ้น probation กลับเทรดเต็มขนาด
    max_lot: float = 1.0
    min_lot: float = 0.01
    contract_size: float = 100.0  # XAUUSD: 1 lot = 100 oz


@dataclass
class OrderPlan:
    approved: bool
    lot: float = 0.0
    risk_amount: float = 0.0
    reason: str = ""


class RiskManager:
    def __init__(self, config: RiskConfig):
        self.config = config

    def volatility_scale(self, atr: float, atr_median: float) -> float:
        """ตัวคูณ risk ตามความผันผวน (ใช้เมื่อ sizing_mode=vol_scaled) — ผันผวนสูงกว่าปกติ = เสี่ยงน้อยลง"""
        if self.config.sizing_mode != "vol_scaled" or atr <= 0 or atr_median <= 0:
            return 1.0
        scale = atr_median / atr
        return max(self.config.vol_scale_min, min(self.config.vol_scale_max, scale))

    def drawdown_budget_scale(self, current_drawdown_pct: float) -> float:
        """ตัวคูณ risk ตามพื้นที่ว่างก่อนชนเพดาน MaxDD (ใช้เมื่อ dd_targeting=True)

        used = สัดส่วน MaxDD ที่ใช้ไปแล้วเทียบเพดาน (0=พึ่งเริ่ม, 1=ชนเพดานพอดี)
        - used <= headroom: boost ลดหลั่นจาก boost_cap ลงมา 1.0 (มีกันชนเยอะ กล้าเสี่ยงเพิ่มได้)
        - used > headroom:  ลดเป็นเส้นตรงจาก 1.0 ลงมา floor (ใกล้เพดาน ต้องระมัดระวังขึ้น)
        """
        if not self.config.dd_targeting or self.config.max_drawdown_pct <= 0:
            return 1.0
        used = max(0.0, min(1.0, current_drawdown_pct / self.config.max_drawdown_pct))
        headroom = self.config.dd_budget_headroom
        if used <= headroom:
            t = used / headroom if headroom > 0 else 1.0
            return self.config.dd_budget_boost_cap - (self.config.dd_budget_boost_cap - 1.0) * t
        t = (used - headroom) / (1.0 - headroom) if headroom < 1.0 else 1.0
        return 1.0 - (1.0 - self.config.dd_budget_floor) * t

    def size_position(
        self, entry: float, sl: float, balance: float, risk_scale: float = 1.0
    ) -> OrderPlan:
        sl_distance = abs(entry - sl)
        if sl_distance <= 0:
            return OrderPlan(approved=False, reason="sl_distance ต้องมากกว่า 0")

        risk_amount = balance * (self.config.risk_per_trade_pct / 100.0) * risk_scale
        lot = risk_amount / (sl_distance * self.config.contract_size)
        lot = max(self.config.min_lot, min(self.config.max_lot, round(lot, 2)))

        if lot < self.config.min_lot:
            return OrderPlan(approved=False, reason="lot ต่ำกว่าขั้นต่ำที่โบรกรับได้")

        reason = "ok" if risk_scale == 1.0 else f"ok (vol scale {risk_scale:.2f})"
        return OrderPlan(approved=True, lot=lot, risk_amount=risk_amount, reason=reason)

    def check_drawdown(self, balance: float, peak_balance: float) -> tuple[bool, str]:
        """คืน (ok_to_trade, reason) — ok_to_trade=False ถ้าชน max_drawdown_pct (kill switch ถาวร)"""
        if peak_balance <= 0:
            return True, "ok"
        drawdown_pct = (peak_balance - balance) / peak_balance * 100.0
        if drawdown_pct >= self.config.max_drawdown_pct:
            return False, f"drawdown {drawdown_pct:.1f}% เกินเพดาน {self.config.max_drawdown_pct}%"
        return True, "ok"

    def check_daily_loss(self, balance: float, day_start_balance: float) -> tuple[bool, str]:
        """ขาดทุนวันนี้ถึงลิมิตไหม — ถ้าถึง พักที่เหลือของวัน (SOP ข้อ 4: Risk ต่อวัน)"""
        if self.config.max_daily_loss_pct is None or day_start_balance <= 0:
            return True, "ok"
        loss_pct = (day_start_balance - balance) / day_start_balance * 100.0
        if loss_pct >= self.config.max_daily_loss_pct:
            return False, f"ขาดทุนวันนี้ {loss_pct:.1f}% ถึงลิมิต {self.config.max_daily_loss_pct}% พักถึงวันใหม่"
        return True, "ok"

    def check_weekly_loss(self, balance: float, week_start_balance: float) -> tuple[bool, str]:
        if self.config.max_weekly_loss_pct is None or week_start_balance <= 0:
            return True, "ok"
        loss_pct = (week_start_balance - balance) / week_start_balance * 100.0
        if loss_pct >= self.config.max_weekly_loss_pct:
            return False, f"ขาดทุนสัปดาห์นี้ {loss_pct:.1f}% ถึงลิมิต {self.config.max_weekly_loss_pct}% พักถึงสัปดาห์ใหม่"
        return True, "ok"

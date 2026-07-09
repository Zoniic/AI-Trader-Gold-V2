"""State + กติกา "จะเข้าไม้ได้ไหมตอนนี้" ที่ backtest engine และ live_runner ใช้ร่วมกัน

แยกออกมาจาก backtest/engine.py เพื่อให้ live trading เดินตามกฎเดียวกับที่ backtest/validate
ไว้แล้วเป๊ะ (DD halt/probation, daily/weekly loss, cooldown หลังแพ้) — ไม่ต้องเขียนซ้ำสองที่
แล้วเสี่ยง logic เพี้ยนกัน
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from risk.position_sizing import RiskConfig, RiskManager


@dataclass
class GateState:
    """สถานะที่ต้องคงอยู่ข้ามแท่ง (เดิมเป็นตัวแปร local ในลูปของ engine.py)"""

    balance: float
    peak_balance: float = field(default=0.0)
    current_date: object = None
    current_week: object = None
    day_start_balance: float = 0.0
    week_start_balance: float = 0.0
    cooldown_until: int = -1
    in_probation: bool = False
    probation_events: int = 0

    def __post_init__(self) -> None:
        if self.peak_balance <= 0:
            self.peak_balance = self.balance
        if self.day_start_balance <= 0:
            self.day_start_balance = self.balance
        if self.week_start_balance <= 0:
            self.week_start_balance = self.balance


@dataclass
class GateResult:
    ok: bool
    reason: str = "ok"
    risk_scale: float = 1.0
    halted: bool = False  # True = kill-switch ถาวร (permanent mode) ต้องหยุดเทรดทีมนี้เลย


def roll_calendar(state: GateState, bar_time: pd.Timestamp) -> None:
    """เรียกทุกแท่งก่อนเช็คอื่นๆ — รีเซ็ต day/week start balance เมื่อขึ้นวัน/สัปดาห์ใหม่"""
    if bar_time.date() != state.current_date:
        state.current_date = bar_time.date()
        state.day_start_balance = state.balance
    iso_week = bar_time.isocalendar()[:2]
    if iso_week != state.current_week:
        state.current_week = iso_week
        state.week_start_balance = state.balance


def check_gate(
    state: GateState,
    risk: RiskManager,
    risk_cfg: RiskConfig,
    bar_idx: int,
    bar_time: pd.Timestamp,
    regime: str | None,
    allowed_regimes: set[str] | None,
    blocked_hours: set[int] | None,
    disable_dd_halt: bool = False,
) -> GateResult:
    """เช็คทุกด่านก่อนอนุญาตให้ประเมิน signal — เหมือน backtest/engine.py ทุกประการ

    คืน GateResult(ok=False) ถ้าด่านใดด่านหนึ่งบล็อก (พร้อมเหตุผล) ไม่งั้น ok=True + risk_scale
    ที่ต้องคูณเข้ากับ position sizing (จาก probation mode)
    """
    ok_to_trade, dd_reason = risk.check_drawdown(state.balance, state.peak_balance)
    cur_dd = (
        (state.peak_balance - state.balance) / state.peak_balance * 100.0
        if state.peak_balance > 0
        else 0.0
    )
    if not ok_to_trade and not disable_dd_halt:
        if risk_cfg.dd_halt_mode == "auto_recover":
            if not state.in_probation:
                state.in_probation = True
                state.probation_events += 1
        else:
            return GateResult(ok=False, reason=dd_reason, halted=True)

    if state.in_probation and cur_dd < risk_cfg.dd_resume_pct:
        state.in_probation = False

    day_ok, day_reason = risk.check_daily_loss(state.balance, state.day_start_balance)
    if not day_ok:
        return GateResult(ok=False, reason=day_reason)
    week_ok, week_reason = risk.check_weekly_loss(state.balance, state.week_start_balance)
    if not week_ok:
        return GateResult(ok=False, reason=week_reason)

    if bar_idx < state.cooldown_until:
        return GateResult(ok=False, reason="cooldown หลังแพ้")

    if allowed_regimes is not None and regime not in allowed_regimes:
        return GateResult(ok=False, reason=f"regime {regime} ไม่ถนัด")

    if blocked_hours is not None and bar_time.hour in blocked_hours:
        return GateResult(ok=False, reason=f"ชั่วโมง {bar_time.hour} ถูกบล็อก")

    risk_scale = 1.0
    if state.in_probation:
        risk_scale *= risk_cfg.dd_probation_scale
    return GateResult(ok=True, risk_scale=risk_scale)


def on_trade_closed(
    state: GateState, pnl: float, exit_idx: int, cooldown_bars_after_loss: int
) -> None:
    """เรียกหลังไม้ปิด — อัปเดต balance/peak + ตั้ง cooldown ถ้าแพ้"""
    state.balance += pnl
    state.peak_balance = max(state.peak_balance, state.balance)
    if pnl < 0 and cooldown_bars_after_loss > 0:
        state.cooldown_until = exit_idx + 1 + cooldown_bars_after_loss

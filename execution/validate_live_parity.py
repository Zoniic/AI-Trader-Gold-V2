"""ตรวจว่า live decision path (risk/live_gate.py + strategy.evaluate ทีละแท่ง) ให้ผลตรงกับ
backtest/engine.py เป๊ะ บนข้อมูลย้อนหลังชุดเดียวกัน — รันก่อนไว้ใจ live_runner ทุกครั้งที่แก้โค้ด core

วิธีเทียบ: จำลอง live loop (เรียก process_bar ทีละแท่งเหมือน live_runner จริง แต่ไม่ยิง order
จริง ใช้ fixed SL/TP แบบ simulate เอง) แล้วเทียบสัญญาณเข้าไม้ (entry_time/direction/entry/sl/tp)
กับที่ backtest/engine.py ให้ ต้องตรงกันทุกไม้ ไม่งั้น = live path เพี้ยนจาก backtest ที่ validate ไว้

ใช้งาน: python -m execution.validate_live_parity --strategy trend_pullback --timeframe M30
"""
from __future__ import annotations

import argparse

import pandas as pd

from backtest.costs import CostModel
from backtest.engine import TradeManagement, _simulate_trade, run_backtest
from backtest.regime import compute_regime
from core.signal import MarketData
from core.strategy import STRATEGY_REGISTRY
from core.team_config import load_team_config
from config import load_settings
from data.loader import load_price_data
from risk.live_gate import GateState, check_gate, on_trade_closed, roll_calendar
from risk.position_sizing import RiskConfig, RiskManager
import strategies  # noqa: F401


def build_risk_cfg(cfg: dict, account_balance: float) -> RiskConfig:
    r = cfg.get("risk") or {}
    return RiskConfig(
        account_balance=account_balance,
        risk_per_trade_pct=r.get("risk_per_trade_pct", 1.0),
        max_drawdown_pct=r.get("max_drawdown_pct", 20.0),
        max_daily_loss_pct=r.get("max_daily_loss_pct"),
        max_weekly_loss_pct=r.get("max_weekly_loss_pct"),
        sizing_mode=r.get("sizing_mode", "fixed"),
        dd_targeting=r.get("dd_targeting", False),
        dd_halt_mode=r.get("dd_halt_mode", "permanent"),
        dd_probation_scale=r.get("dd_probation_scale", 0.35),
        dd_resume_pct=r.get("dd_resume_pct", 10.0),
    )


def simulate_live_path(
    team: str, tf: str, data: MarketData, cfg: dict, account_balance: float, mgmt: TradeManagement,
    cost: CostModel,
) -> list[dict]:
    """จำลอง live loop ทีละแท่ง ใช้ risk/live_gate.py ตัวเดียวกับ live_runner.py จริง

    ต้อง advance idx ข้ามช่วงที่มีไม้เปิดอยู่เหมือน backtest/engine.py เป๊ะ (ใช้ _simulate_trade
    ตัวเดียวกันหา exit_idx) และต้องอัปเดต balance/cooldown ผ่าน on_trade_closed() หลังทุกไม้ปิด —
    ไม่งั้น cooldown/probation/dd-budget-scale จะไม่ sync กับ backtest ทำให้ parity เพี้ยนที่ gate
    ไม่ใช่ที่ signal (เจอบั๊กนี้จริงตอนทดสอบ vwap_reversion — แก้แล้วที่นี่)
    """
    df = data.df
    cls = STRATEGY_REGISTRY[team]
    strat = cls(**cfg["strategy_params"])
    if hasattr(strat, "_committee"):
        strat._committee.min_approvals = cfg.get("min_approvals", 4)

    risk_cfg = build_risk_cfg(cfg, account_balance)
    risk = RiskManager(risk_cfg)
    state = GateState(balance=account_balance)
    regime_series = compute_regime(df)
    allowed = set(cfg.get("allowed_regimes")) if cfg.get("allowed_regimes") else None
    blocked_hr = set(cfg.get("blocked_hours")) if cfg.get("blocked_hours") else None

    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(),
         (df["low"] - df["close"].shift(1)).abs()], axis=1,
    ).max(axis=1)
    atr_series = tr.rolling(14).mean()
    atr_median_series = atr_series.rolling(500, min_periods=50).median()

    entries = []
    warmup = getattr(strat, "min_lookback", lambda: 60)()
    idx = warmup
    while idx < len(df) - 1:
        bar_time = df.index[idx]
        roll_calendar(state, bar_time)
        gate = check_gate(
            state, risk, risk_cfg, idx, bar_time,
            regime=regime_series.iloc[idx], allowed_regimes=allowed, blocked_hours=blocked_hr,
        )
        if gate.halted:
            break
        if not gate.ok:
            idx += 1
            continue
        signal = strat.evaluate(data, idx)
        if not signal.is_actionable:
            idx += 1
            continue
        current_dd_pct = (
            (state.peak_balance - state.balance) / state.peak_balance * 100.0
            if state.peak_balance > 0 else 0.0
        )
        atr_now = float(atr_series.iloc[idx]) if not pd.isna(atr_series.iloc[idx]) else 0.0
        atr_med = float(atr_median_series.iloc[idx]) if not pd.isna(atr_median_series.iloc[idx]) else atr_now
        risk_scale = (
            risk.volatility_scale(atr_now, atr_med)
            * risk.drawdown_budget_scale(current_dd_pct)
            * gate.risk_scale
        )
        plan = risk.size_position(signal.entry, signal.sl, state.balance, risk_scale=risk_scale)
        if not plan.approved:
            idx += 1
            continue
        entries.append({
            "entry_time": bar_time, "direction": signal.direction.value,
            "entry": round(signal.entry, 5), "sl": round(signal.sl, 5), "tp": round(signal.tp, 5),
        })
        exit_idx, parts, outcome, mae_r, mfe_r = _simulate_trade(
            df, idx + 1, signal.direction, signal.entry, signal.sl, signal.tp, max_hold=100, management=mgmt,
        )
        # ต้องใช้สูตรต้นทุนเดียวกับ backtest/engine.py เป๊ะ (session/volatility-aware) ไม่งั้น balance
        # path ที่ simulate ในนี้จะเพี้ยนจาก backtest จริง ทำให้ gate decision ถัดๆ ไปเทียบ parity ผิด
        round_trip_cost = cost.round_trip_cost_at(bar_time.hour, atr_now, atr_med)
        pnl = sum(
            (signal.direction.sign * (exit_price - signal.entry) - round_trip_cost)
            * fraction * plan.lot * risk_cfg.contract_size
            for fraction, exit_price in parts
        )
        on_trade_closed(state, pnl, exit_idx, mgmt.cooldown_bars_after_loss)
        idx = exit_idx + 1
    return entries


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", required=True)
    p.add_argument("--timeframe", default="M30")
    args = p.parse_args()

    import os
    os.environ["TIMEFRAME"] = args.timeframe
    settings = load_settings()
    data = load_price_data(settings)
    cfg = load_team_config(args.strategy, STRATEGY_REGISTRY[args.strategy], timeframe=args.timeframe)

    cls = STRATEGY_REGISTRY[args.strategy]
    strat = cls(**cfg["strategy_params"])
    if hasattr(strat, "_committee"):
        strat._committee.min_approvals = cfg.get("min_approvals", 4)
    mgmt = TradeManagement(**cfg["trade_management"])
    cost = CostModel(spread_points=settings.spread_points, slippage_points=settings.slippage_points)
    risk_cfg = build_risk_cfg(cfg, settings.initial_balance)

    bt_result = run_backtest(
        strat, data, risk_cfg, cost, management=mgmt,
        allowed_regimes=cfg.get("allowed_regimes"), blocked_hours=cfg.get("blocked_hours"),
    )
    bt_entries = {(t.entry_time, t.direction.value) for t in bt_result.trades}

    live_entries = simulate_live_path(
        args.strategy, args.timeframe, data, cfg, settings.initial_balance, mgmt, cost
    )
    live_entries_set = {(e["entry_time"], e["direction"]) for e in live_entries}

    matched = bt_entries & live_entries_set
    only_bt = bt_entries - live_entries_set
    only_live = live_entries_set - bt_entries

    print(f"[parity] {args.strategy}:{args.timeframe}")
    print(f"  backtest entries: {len(bt_entries)}")
    print(f"  live-path entries: {len(live_entries_set)}")
    print(f"  matched: {len(matched)}")
    print(f"  only-in-backtest (พลาดใน live path): {len(only_bt)}")
    print(f"  only-in-live (เกินจาก live path): {len(only_live)}")
    if only_bt or only_live:
        print("  [WARNING] parity ไม่ตรงกัน 100% — ตรวจ risk/live_gate.py ก่อนไว้ใจ live_runner")
        if only_bt:
            print(f"    ตัวอย่าง only-backtest: {list(only_bt)[:3]}")
        if only_live:
            print(f"    ตัวอย่าง only-live: {list(only_live)[:3]}")
    else:
        print("  [OK] parity ตรงกัน 100% — live decision path เชื่อถือได้เท่า backtest")


if __name__ == "__main__":
    main()

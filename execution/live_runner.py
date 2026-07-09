"""Paper/demo forward-runner: ต่อ strategy+risk เดิม (เหมือน backtest เป๊ะ) เข้ากับ MT5 demo จริง

กติกาความปลอดภัย: dry_run=True เป็นดีฟอลต์เสมอ, broker.py เช็ค _assert_demo() ทุกครั้งก่อนยิง
— ยิงบัญชีจริงไม่ได้แม้ตั้งใจ (raise NotDemoAccountError ทันที)

Loop ทำงานยังไง (ต่อทีมที่ config ไว้):
1. ทุก poll_interval วินาที เช็คว่ามีแท่งใหม่ "ปิดแล้ว" หรือยัง (ตัดแท่งกำลังก่อตัวทิ้งเสมอ)
2. ถ้ามี: ต่อเข้า buffer แล้วเรียก strategy.evaluate(data, idx) ที่แท่งปิดล่าสุด — ใช้ risk/live_gate.py
   ตัวเดียวกับ backtest/engine.py จึงพฤติกรรมตรงกันเป๊ะ (DD halt/probation, cooldown, regime/hour gate)
3. ถ้าผ่านทุกด่าน + risk อนุมัติ lot → broker.send_order() (มี SL/TP ฝังไว้ในออเดอร์ ให้ MT5 จัดการเอง
   ไม่ simulate exit เองแบบ backtest — v1 ยังไม่รองรับ partial-TP/trailing แบบ dynamic)
4. ทุกรอบ poll เช็ค position ที่เปิดค้างไว้ด้วยว่าปิดหรือยัง (broker.get_position) ถ้าปิดแล้ว
   ดึง pnl จริงจาก deal history มาอัปเดต GateState + บันทึกไม้ลง DB

ใช้งาน: python -m execution.live_runner --dry-run          (ปลอดภัยสุด ไม่ยิงจริง)
        python -m execution.live_runner --live               (ยิงเข้า demo จริง ต้องพิมพ์ยืนยัน)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from backtest.costs import CostModel
from backtest.engine import Trade
from backtest.regime import compute_regime
from core.signal import Direction, MarketData, Signal
from core.strategy import STRATEGY_REGISTRY, Strategy
from core.team_config import load_team_config
from config import load_settings
from data.mt5_loader import TIMEFRAME_MAP
from execution.broker import MT5Broker, NotDemoAccountError
from persistence.db import RunLogger
from risk.live_gate import GateState, check_gate, on_trade_closed, roll_calendar
from risk.position_sizing import RiskConfig, RiskManager
import strategies  # noqa: F401 เติม registry

DEFAULT_ROSTER = [
    ("trend_pullback", "M30"), ("london_breakout", "M30"), ("trend_pullback", "H1"),
    ("rsi_divergence", "M30"), ("donchian_breakout", "H1"), ("ema_cross", "M30"),
    ("vwap_reversion", "H1"), ("volatility_breakout", "H1"),
]
POLL_INTERVAL_SEC = 30


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
        dd_budget_headroom=r.get("dd_budget_headroom", 0.3),
        dd_budget_boost_cap=r.get("dd_budget_boost_cap", 1.3),
        dd_budget_floor=r.get("dd_budget_floor", 0.4),
        dd_halt_mode=r.get("dd_halt_mode", "permanent"),
        dd_probation_scale=r.get("dd_probation_scale", 0.35),
        dd_resume_pct=r.get("dd_resume_pct", 10.0),
    )


@dataclass
class LiveTeam:
    team: str
    timeframe: str
    strategy: Strategy
    cfg: dict
    df: pd.DataFrame
    last_bar_time: pd.Timestamp
    state: GateState
    risk: RiskManager
    risk_cfg: RiskConfig
    logger: RunLogger
    open_ticket: int | None = None
    open_signal_id: int | None = None
    open_entry_meta: dict = field(default_factory=dict)


def bootstrap_team(
    broker: MT5Broker, team: str, tf: str, symbol: str, account_balance: float, db_path: str,
    lookback: int = 800,
) -> LiveTeam:
    cls = STRATEGY_REGISTRY[team]
    cfg = load_team_config(team, cls, timeframe=tf)
    strat = cls(**cfg["strategy_params"])
    if hasattr(strat, "_committee"):
        strat._committee.min_approvals = cfg.get("min_approvals", 4)

    tf_const_name = TIMEFRAME_MAP[tf]
    import MetaTrader5 as mt5
    tf_const = getattr(mt5, tf_const_name)
    rates = broker.latest_closed_bars(symbol, tf_const, lookback)
    if rates is None:
        raise RuntimeError(f"ดึงข้อมูล {symbol} {tf} จาก MT5 ไม่ได้ (bootstrap {team})")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.set_index("time").rename(columns={"tick_volume": "volume"})[
        ["open", "high", "low", "close", "volume"]
    ]

    risk_cfg = build_risk_cfg(cfg, account_balance)
    run_id = f"live_{team}_{tf}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    logger = RunLogger(db_path, run_id=run_id)
    logger.start_run(team, account_balance, timeframe=tf, config=json.dumps(cfg, ensure_ascii=False))

    return LiveTeam(
        team=team, timeframe=tf, strategy=strat, cfg=cfg, df=df,
        last_bar_time=df.index[-1],
        state=GateState(balance=account_balance),
        risk=RiskManager(risk_cfg), risk_cfg=risk_cfg, logger=logger,
    )


def poll_new_bar(broker: MT5Broker, lt: LiveTeam, symbol: str, lookback: int = 800) -> bool:
    """เช็คว่ามีแท่งใหม่ปิดหรือยัง ถ้ามีต่อเข้า buffer แล้วคืน True"""
    import MetaTrader5 as mt5
    tf_const = getattr(mt5, TIMEFRAME_MAP[lt.timeframe])
    rates = broker.latest_closed_bars(symbol, tf_const, lookback)
    if rates is None:
        return False
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.set_index("time").rename(columns={"tick_volume": "volume"})[
        ["open", "high", "low", "close", "volume"]
    ]
    if df.index[-1] <= lt.last_bar_time:
        return False  # ยังไม่มีแท่งใหม่ปิด
    lt.df = df
    lt.last_bar_time = df.index[-1]
    return True


def reconcile_open_position(broker: MT5Broker, lt: LiveTeam, dry_run: bool) -> None:
    """เช็ค position ที่เปิดค้างไว้ ถ้าปิดไปแล้ว (โดน SL/TP จริงใน MT5) ดึง pnl มาอัปเดต state + log"""
    if lt.open_ticket is None:
        return
    if dry_run:
        return  # dry_run ไม่มี ticket จริงใน MT5 ให้เช็ค
    pos = broker.get_position(lt.open_ticket)
    if pos is not None:
        return  # ยังเปิดอยู่
    pnl = broker.get_closed_deal_pnl(lt.open_ticket)
    if pnl is None:
        return  # ยังหา deal history ไม่เจอ รอรอบถัดไป
    exit_idx = len(lt.df) - 1
    meta = lt.open_entry_meta
    outcome = "tp" if pnl >= 0 else "sl"  # ประมาณจากผลจริง (ไม่รู้ว่าโดน SL/TP เป๊ะจาก deal เดียว)
    trade = Trade(
        direction=meta["direction"], entry_time=lt.df.index[meta["entry_idx"]], entry=meta["entry"],
        sl=meta["sl"], tp=meta.get("tp", meta["sl"]), lot=meta.get("lot", 0.0),
        exit_time=lt.df.index[exit_idx], exit_price=meta.get("entry", 0.0), pnl=pnl, outcome=outcome,
        regime="", review="ปิดจาก MT5 จริง (SL/TP ของ broker) — ไม่ได้ simulate",
    )
    if lt.open_signal_id is not None:
        lt.logger.log_trade(lt.open_signal_id, trade)
    on_trade_closed(lt.state, pnl, exit_idx, lt.cfg.get("trade_management", {}).get("cooldown_bars_after_loss", 0))
    print(f"[live] {lt.team}:{lt.timeframe} ไม้ ticket={lt.open_ticket} ปิดแล้ว pnl={pnl:.2f} "
          f"balance={lt.state.balance:.2f}", flush=True)
    lt.open_ticket = None
    lt.open_signal_id = None
    lt.open_entry_meta = {}


def process_bar(broker: MT5Broker, lt: LiveTeam, symbol: str, cost: CostModel, dry_run: bool) -> None:
    if lt.open_ticket is not None:
        return  # v1: ทีมละ 1 ไม้พร้อมกัน (ไม่ pyramiding) — กันความซับซ้อนของ partial-fill state

    data = MarketData(df=lt.df, symbol=symbol)
    idx = len(lt.df) - 1
    bar_time = lt.df.index[idx]
    roll_calendar(lt.state, bar_time)

    regime_series = compute_regime(lt.df)
    allowed = set(lt.cfg.get("allowed_regimes")) if lt.cfg.get("allowed_regimes") else None
    blocked_hr = set(lt.cfg.get("blocked_hours")) if lt.cfg.get("blocked_hours") else None

    gate = check_gate(
        lt.state, lt.risk, lt.risk_cfg, idx, bar_time,
        regime=regime_series.iloc[idx], allowed_regimes=allowed, blocked_hours=blocked_hr,
    )
    if gate.halted:
        print(f"[live] {lt.team}:{lt.timeframe} kill-switch: {gate.reason} — หยุดเทรดทีมนี้ถาวร", flush=True)
        return
    if not gate.ok:
        return

    signal: Signal = lt.strategy.evaluate(data, idx)
    if not signal.is_actionable:
        return

    current_balance = lt.state.balance if dry_run else broker.account_balance()
    lt.state.balance = current_balance
    plan = lt.risk.size_position(signal.entry, signal.sl, current_balance, risk_scale=gate.risk_scale)
    if not plan.approved:
        print(f"[live] {lt.team}:{lt.timeframe} signal แต่ risk ปฏิเสธ: {plan.reason}", flush=True)
        return

    signal_id = lt.logger.log_signal(
        bar_time=bar_time, strategy=lt.strategy.name, direction=signal.direction.value,
        entry=signal.entry, sl=signal.sl, tp=signal.tp, reason=signal.reason,
        discussion=json.dumps(signal.meta.get("discussion"), ensure_ascii=False)
        if signal.meta.get("discussion") else None,
    )
    lt.logger.log_decision(signal_id, approved=True, reason=plan.reason, lot=plan.lot)

    result = broker.send_order(symbol, signal.direction, plan.lot, signal.sl, signal.tp)
    if not result.success:
        print(f"[live] {lt.team}:{lt.timeframe} ส่งออเดอร์ล้มเหลว: {result.message}", flush=True)
        return

    print(f"[live] {lt.team}:{lt.timeframe} เข้าไม้ {signal.direction.value} {plan.lot} lot "
          f"@ {signal.entry} sl={signal.sl} tp={signal.tp} ticket={result.ticket} ({result.message})",
          flush=True)
    lt.open_ticket = result.ticket
    lt.open_signal_id = signal_id
    lt.open_entry_meta = {
        "entry_idx": idx, "entry": signal.entry, "sl": signal.sl, "tp": signal.tp,
        "lot": plan.lot, "direction": signal.direction,
    }


def run(roster: list[tuple[str, str]], dry_run: bool, poll_interval: int) -> None:
    settings = load_settings()
    broker = MT5Broker(dry_run=dry_run)
    login = settings.mt5.login
    if login is not None:
        broker.connect(login, settings.mt5.password, settings.mt5.server)
    else:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            raise ConnectionError(f"เชื่อมต่อ MT5 ไม่สำเร็จ: {mt5.last_error()}")
        broker._mt5 = mt5
        broker._connected = True
        broker._assert_demo()

    print(f"[live] เชื่อมต่อ MT5 สำเร็จ — dry_run={dry_run} roster={roster}", flush=True)
    account_balance = broker.account_balance() if not dry_run else settings.initial_balance
    cost = CostModel(spread_points=settings.spread_points, slippage_points=settings.slippage_points)

    teams = [
        bootstrap_team(broker, team, tf, settings.symbol, account_balance, settings.log_db_path)
        for team, tf in roster
    ]
    print(f"[live] bootstrap เสร็จ {len(teams)} ทีม เริ่ม poll ทุก {poll_interval}s (Ctrl+C หยุด)", flush=True)

    cycle = 0
    try:
        while True:
            cycle += 1
            for lt in teams:
                try:
                    reconcile_open_position(broker, lt, dry_run)
                    if poll_new_bar(broker, lt, settings.symbol):
                        process_bar(broker, lt, settings.symbol, cost, dry_run)
                except NotDemoAccountError:
                    raise
                except Exception as exc:  # ทีมเดียวพังไม่ควรทำให้ทีมอื่นหยุด
                    print(f"[live] {lt.team}:{lt.timeframe} error: {exc}", flush=True)
            if cycle % 20 == 0:  # heartbeat กันสงสัยว่า process ตายไปหรือยัง (ทุก ~cycle*poll_interval วิ)
                print(
                    f"[live] heartbeat cycle={cycle} เวลา={datetime.now().strftime('%H:%M:%S')} "
                    f"ทีมที่ยังมีไม้เปิด={sum(1 for lt in teams if lt.open_ticket is not None)}/{len(teams)}",
                    flush=True,
                )
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        print("[live] หยุดตามคำสั่งผู้ใช้", flush=True)
    finally:
        for lt in teams:
            lt.logger.close()
        broker.disconnect()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="ไม่ยิงออเดอร์จริง (ดีฟอลต์)")
    mode.add_argument("--live", action="store_true", help="ยิงออเดอร์เข้า MT5 demo จริง (ยังต้องเป็น demo)")
    p.add_argument("--teams", default=None, help="เช่น trend_pullback:M30,london_breakout:M30 (ว่าง=พอร์ตหลัก 8 ทีม)")
    p.add_argument("--poll-interval", type=int, default=POLL_INTERVAL_SEC)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    dry_run = not args.live
    if args.teams:
        roster = [tuple(t.split(":")) for t in args.teams.split(",")]
    else:
        roster = DEFAULT_ROSTER

    if not dry_run:
        confirm = input(
            "!!! กำลังจะยิงออเดอร์จริงเข้าบัญชี MT5 (ต้องเป็น demo เท่านั้น) พิมพ์ 'ยืนยัน' เพื่อดำเนินการ: "
        )
        if confirm.strip() != "ยืนยัน":
            print("ยกเลิก", flush=True)
            sys.exit(0)

    run(roster, dry_run=dry_run, poll_interval=args.poll_interval)


if __name__ == "__main__":
    main()

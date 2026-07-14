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
from backtest.engine import Trade, TradeManagement
from backtest.regime import compute_regime
from core.signal import Direction, MarketData, Signal
from core.strategy import STRATEGY_REGISTRY, Strategy
from core.team_config import load_team_config
from config import load_settings
from data.mt5_loader import TIMEFRAME_MAP
from execution.alerts import send_discord_alert
from execution.broker import MT5Broker, NotDemoAccountError, compute_magic
from persistence.db import RunLogger, find_open_trade, load_gate_state, save_gate_state
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
class ManageState:
    """สถานะ trailing/partial ของไม้ที่เปิดอยู่ — mirror ตัวแปร local ใน backtest/engine.py::_simulate_trade
    ทุกจุด เพื่อให้ live เดินตาม logic เดียวกับที่ backtest วัดผลไว้เป๊ะ (ไม่ใช่แค่ fixed SL/TP)
    """

    direction: Direction
    entry: float
    original_sl: float
    tp: float
    lot: float
    current_sl: float = 0.0
    remaining_lot: float = 0.0
    partial_done: bool = False
    trail_active: bool = False
    trail_moved: bool = False
    extreme: float = 0.0
    partial_level: float | None = None
    trail_dist: float | None = None
    activate_level: float = 0.0

    def __post_init__(self) -> None:
        self.current_sl = self.original_sl
        self.remaining_lot = self.lot
        self.extreme = self.entry


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
    management: TradeManagement
    open_ticket: int | None = None
    open_signal_id: int | None = None
    open_entry_meta: dict = field(default_factory=dict)
    manage_state: ManageState | None = None
    open_trade_id: int | None = None
    pending_close_attempts: int = 0
    magic: int = 0
    symbol: str = ""


def bootstrap_team(
    broker: MT5Broker, team: str, tf: str, symbol: str, account_balance: float, db_path: str,
    lookback: int = 800, dry_run: bool = True,
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
    logger.start_run(team, account_balance, timeframe=tf, config=json.dumps(cfg, ensure_ascii=False), symbol=symbol)

    # โหลด GateState เดิม (cooldown/probation/peak_balance) ที่บันทึกไว้ก่อน process ตาย/restart —
    # ถ้าไม่เคยมี (ทีมใหม่) จะได้ None แล้วสร้างสถานะเปล่าตามปกติ balance ใช้ค่าจาก broker เสมอ
    # (ground truth ปัจจุบัน) แต่ peak_balance/cooldown/probation ต้อง "จำ" ต่อจากเดิมถึงจะมีความหมาย
    saved_state = load_gate_state(db_path, team, tf)
    if saved_state is not None:
        saved_state.balance = account_balance
        # cooldown_until เป็น bar-index สัมพัทธ์กับ DataFrame ของ process เดิม — พอ restart แล้ว
        # bootstrap ใหม่ index จะเริ่มนับใหม่ ตัวเลขเดิมจึงไม่มีความหมาย (อาจทำให้ cooldown ค้างตลอดไป
        # หรือหลุดก่อนเวลาแบบสุ่ม) ปลอดภัยกว่าคือรีเซ็ตเป็น -1 (ไม่มี cooldown ค้าง) แล้วให้ cooldown รอบ
        # ใหม่ทำงานตามปกติเมื่อแพ้ไม้ถัดไป — ส่วน peak_balance/probation/day-week balance restore ได้
        # ปลอดภัยเพราะอิงปฏิทิน/เงินจริง ไม่ใช่ bar-index
        saved_state.cooldown_until = -1
        state = saved_state
        print(f"[live] {team}:{tf} โหลด GateState เดิมกลับมา — peak_balance={state.peak_balance:.2f} "
              f"in_probation={state.in_probation} probation_events={state.probation_events}", flush=True)
    else:
        state = GateState(balance=account_balance)

    lt = LiveTeam(
        team=team, timeframe=tf, strategy=strat, cfg=cfg, df=df,
        last_bar_time=df.index[-1],
        state=state,
        risk=RiskManager(risk_cfg), risk_cfg=risk_cfg, logger=logger,
        management=TradeManagement(**cfg["trade_management"]),
        magic=compute_magic(team, tf),
        symbol=symbol,
    )

    # ไม้ที่เปิดค้างไว้ตอน process ตาย/restart ยังเปิดอยู่จริงใน MT5 แต่ LiveTeam ใหม่ไม่รู้จัก
    # ticket เดิม (open_ticket เริ่มที่ None เสมอ) — ถ้าไม่ดึงกลับมา reconcile_open_position()
    # จะเช็ค `if lt.open_ticket is None: return` แล้วกลายเป็น no-op ถาวรสำหรับไม้นั้น (ราคา/กำไรลอย
    # ค้างค่าเดิมไม่อัปเดตอีกเลยจนกว่าไม้จะปิด) เลยต้องหาไม้ที่ยัง exit_time IS NULL ของทีมนี้จาก DB
    # แล้วเช็คกับ broker ว่ายังเปิดอยู่จริงหรือเปล่าก่อน re-attach
    if not dry_run:
        open_row = find_open_trade(db_path, team, tf)
        if open_row is not None:
            pos = broker.get_position(open_row["ticket"], expected_magic=lt.magic)
            if pos is not None:
                direction = Direction.BUY if open_row["direction"] == "BUY" else Direction.SELL
                lt.open_ticket = open_row["ticket"]
                lt.open_trade_id = open_row["id"]
                lt.open_signal_id = open_row["signal_id"]
                lt.open_entry_meta = {
                    "entry_idx": len(df) - 1, "entry": open_row["entry"], "sl": open_row["sl"],
                    "tp": open_row["tp"], "lot": open_row["lot"], "direction": direction,
                }
                risk_dist = abs(open_row["entry"] - open_row["sl"])
                mgmt = lt.management
                lt.manage_state = ManageState(
                    direction=direction, entry=open_row["entry"], original_sl=open_row["sl"],
                    tp=open_row["tp"], lot=open_row["lot"],
                    partial_level=(
                        open_row["entry"] + direction.sign * risk_dist * mgmt.partial_tp_r
                        if mgmt.partial_tp_r is not None else None
                    ),
                    trail_dist=(risk_dist * mgmt.trailing_stop_r if mgmt.trailing_stop_r is not None else None),
                    activate_level=open_row["entry"] + direction.sign * risk_dist * mgmt.trailing_activate_r,
                )
                # broker SL ปัจจุบันอาจถูกเลื่อนไปแล้ว (BE/trailing) ก่อน restart — ใช้ค่าจริงจาก
                # position แทนค่า original_sl ตอนสร้าง ManageState กันเลื่อน SL ย้อนกลับผิดทาง
                lt.manage_state.current_sl = float(pos.sl) if pos.sl else open_row["sl"]
                # lot ที่เหลือจริงใน broker (pos.volume) อาจน้อยกว่า lot ตอนเปิด (open_row["lot"])
                # ถ้า partial TP ไปแล้วก่อน restart — ต้อง "จำ" ว่า partial_done=True แล้ว ไม่งั้นพอ
                # ราคาแตะ partial_level อีกครั้ง manage_open_position() จะพยายามปิดบางส่วนซ้ำด้วย
                # fraction ที่คำนวณจาก lot เต็ม (ผิด เพราะ lot จริงเหลือน้อยกว่านั้นแล้ว)
                broker_lot = float(pos.volume)
                if broker_lot < open_row["lot"] - 1e-9:
                    lt.manage_state.partial_done = True
                    lt.manage_state.remaining_lot = broker_lot
                print(f"[live] {team}:{tf} โหลดไม้เปิดค้างกลับมา — ticket={open_row['ticket']} "
                      f"entry={open_row['entry']} current_sl={lt.manage_state.current_sl} "
                      f"lot={broker_lot}/{open_row['lot']} partial_done={lt.manage_state.partial_done}", flush=True)

    return lt


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


PENDING_CLOSE_WARN_ATTEMPTS = 10  # ~5 นาทีที่ poll_interval=30s ก่อนแจ้งเตือนว่า deal history ยังไม่ขึ้น


def _close_emoji(pnl: float) -> str:
    return "✅" if pnl >= 0 else "❌"


def _reconcile_dry_run(lt: LiveTeam, cost: CostModel, discord_webhook_url: str | None = None) -> None:
    """dry_run ไม่มี ticket จริงจาก MT5 ให้เช็ค ก่อนหน้านี้ reconcile_open_position() แค่ return
    เฉยๆ ทำให้ current_price/floating_pnl ในหน้า dashboard ไม่เคยอัปเดตเลยตลอดทั้งไม้ (gap ที่เจอ
    ตอน audit) และไม้ dry-run ไม่เคยปิดเองด้วย (ไม่มีอะไรเช็ค SL/TP ให้) เลย simulate ง่ายๆ ตรงนี้:
    อัปเดตราคาจากแท่งล่าสุดทุกรอบ + เช็ค high/low ของแท่งล่าสุดว่าแตะ SL/TP หรือยัง (ไม่ simulate
    intrabar exact เหมือน backtest 100% — พอสำหรับ dry-run ที่จุดประสงค์คือทดสอบ signal/flow ไม่ใช่
    วัดผลลัพธ์ทางการเงินแม่นยำ)
    """
    if lt.open_trade_id is None or lt.df.empty:
        return
    meta = lt.open_entry_meta
    direction: Direction | None = meta.get("direction")
    entry = meta.get("entry")
    sl = meta.get("sl")
    tp = meta.get("tp")
    lot = meta.get("lot")
    if direction is None or entry is None or sl is None or tp is None or lot is None:
        return

    bar = lt.df.iloc[-1]
    sign = direction.sign
    current_price = float(bar["close"])
    floating_pnl = (current_price - entry) * sign * lot * cost.point_value
    lt.logger.update_open_trade(lt.open_trade_id, current_price, floating_pnl)

    high, low = float(bar["high"]), float(bar["low"])
    hit_sl = low <= sl if sign > 0 else high >= sl
    hit_tp = high >= tp if sign > 0 else low <= tp
    if not (hit_sl or hit_tp):
        return
    exit_price = sl if hit_sl else tp  # ถ้าแตะทั้งคู่ในแท่งเดียวกัน ประมาณว่าโดน SL ก่อน (อนุรักษ์นิยม)
    pnl = (exit_price - entry) * sign * lot * cost.point_value
    outcome = "sl" if hit_sl else "tp"
    exit_idx = len(lt.df) - 1
    lt.logger.log_trade_close(
        lt.open_trade_id, exit_time=lt.df.index[exit_idx], exit_price=exit_price, pnl=pnl, outcome=outcome,
    )
    on_trade_closed(lt.state, pnl, exit_idx, lt.cfg.get("trade_management", {}).get("cooldown_bars_after_loss", 0))
    print(f"[live-dry] {lt.team}:{lt.timeframe} (จำลอง) ไม้ปิดแล้ว outcome={outcome} pnl={pnl:.2f} "
          f"balance={lt.state.balance:.2f}", flush=True)
    send_discord_alert(
        f"{_close_emoji(pnl)} **ปิดไม้ (จำลอง)** — `{lt.team}:{lt.timeframe}` {meta['direction'].value} "
        f"{lot} lot @ {exit_price:.2f} outcome={outcome}\nPnL: ${pnl:+.2f} | Balance: ${lt.state.balance:.2f}",
        discord_webhook_url, level="info", dedupe_key=None,
    )
    lt.open_ticket = None
    lt.open_signal_id = None
    lt.open_entry_meta = {}
    lt.manage_state = None
    lt.open_trade_id = None


def reconcile_open_position(
    broker: MT5Broker, lt: LiveTeam, dry_run: bool, cost: CostModel, discord_webhook_url: str | None = None,
) -> None:
    """เช็ค position ที่เปิดค้างไว้ ถ้ายังเปิดอยู่ อัปเดตราคาปัจจุบัน/กำไรลอย
    ถ้าปิดไปแล้ว (โดน SL/TP จริงใน MT5) ดึง pnl มาอัปเดต state + log
    """
    if dry_run:
        _reconcile_dry_run(lt, cost, discord_webhook_url=discord_webhook_url)
        return
    if lt.open_ticket is None:
        return
    pos = broker.get_position(lt.open_ticket, expected_magic=lt.magic)
    if pos is not None:
        if lt.open_trade_id is not None:
            lt.logger.update_open_trade(lt.open_trade_id, float(pos.price_current), float(pos.profit))
        lt.pending_close_attempts = 0
        return  # ยังเปิดอยู่
    pnl = broker.get_closed_deal_pnl(lt.open_ticket)
    if pnl is None:
        # position หายจาก MT5 แล้วแต่ deal history ยังไม่ขึ้น — ปกติแล้วเกิดชั่วครู่แล้วหาย แต่ถ้าค้าง
        # นานผิดปกติ (broker ไม่ sync/บั๊ก) ต้อง "ส่งเสียง" แทนที่จะเงียบไปเรื่อยๆ แบบ no-op ถาวร
        lt.pending_close_attempts += 1
        if lt.pending_close_attempts == PENDING_CLOSE_WARN_ATTEMPTS:
            print(f"[live] {lt.team}:{lt.timeframe} คำเตือน: ticket={lt.open_ticket} หายจาก "
                  f"positions_get แต่หา deal history ไม่เจอมา {lt.pending_close_attempts} รอบติดกัน", flush=True)
            send_discord_alert(
                f"⚠️ **ไม้ค้างสถานะไม่ชัดเจน** — `{lt.team}:{lt.timeframe}` ticket={lt.open_ticket} "
                f"หายจาก MT5 positions แต่หา deal history ยืนยันผลไม่เจอมา {lt.pending_close_attempts} รอบ",
                discord_webhook_url, level="warning",
                dedupe_key=f"pending_close_{lt.team}_{lt.timeframe}_{lt.open_ticket}", dedupe_seconds=1800,
            )
        return  # ยังหา deal history ไม่เจอ รอรอบถัดไป
    lt.pending_close_attempts = 0
    exit_idx = len(lt.df) - 1
    meta = lt.open_entry_meta
    outcome = "tp" if pnl >= 0 else "sl"  # ประมาณจากผลจริง (ไม่รู้ว่าโดน SL/TP เป๊ะจาก deal เดียว)
    if lt.open_trade_id is not None:
        lt.logger.log_trade_close(
            lt.open_trade_id, exit_time=lt.df.index[exit_idx], exit_price=meta.get("entry", 0.0),
            pnl=pnl, outcome=outcome,
        )
    on_trade_closed(lt.state, pnl, exit_idx, lt.cfg.get("trade_management", {}).get("cooldown_bars_after_loss", 0))
    print(f"[live] {lt.team}:{lt.timeframe} ไม้ ticket={lt.open_ticket} ปิดแล้ว pnl={pnl:.2f} "
          f"balance={lt.state.balance:.2f}", flush=True)
    send_discord_alert(
        f"{_close_emoji(pnl)} **ปิดไม้** — `{lt.team}:{lt.timeframe}` ticket={lt.open_ticket} "
        f"outcome={outcome}\nPnL: ${pnl:+.2f} | Balance: ${lt.state.balance:.2f}",
        discord_webhook_url, level="info", dedupe_key=None,
    )
    lt.open_ticket = None
    lt.open_signal_id = None
    lt.open_entry_meta = {}
    lt.manage_state = None
    lt.open_trade_id = None


def manage_open_position(broker: MT5Broker, lt: LiveTeam, symbol: str, dry_run: bool) -> None:
    """ปรับ SL/TP ของไม้ที่เปิดอยู่ตามแท่งที่เพิ่งปิด — mirror _simulate_trade steps 2-4 ใน
    backtest/engine.py (partial TP แล้วเลื่อน BE, trailing stop) เรียกทุกครั้งที่มีแท่งใหม่ปิดและ
    ยังมีไม้เปิดอยู่ (ก่อน reconcile จะเช็คว่าไม้ปิดหรือยังในรอบถัดไป)

    หมายเหตุ: SL/TP เดิม (fixed) ที่ฝังไว้ตอนส่ง order จะถูก MT5 จัดการเองระหว่างแท่ง (real-time)
    ฟังก์ชันนี้แค่ "เลื่อน" SL/TP นั้นตามเงื่อนไข snowball ทุกครั้งที่แท่งใหม่ปิด — ไม่ได้ simulate
    intrabar exact เหมือน backtest 100% (เพราะ live ใช้ order ของ broker จริง) แต่ให้ผลลัพธ์เชิงพฤติกรรม
    ตรงกับที่ backtest วัดไว้ (ปรับ SL หลังแท่งปิด เหมือน step 4 ของ _simulate_trade)
    """
    if dry_run or lt.open_ticket is None or lt.manage_state is None:
        return
    m = lt.manage_state
    mgmt = lt.management
    bar = lt.df.iloc[-1]
    high, low = float(bar["high"]), float(bar["low"])
    sign = m.direction.sign

    # 2) partial TP (ครั้งเดียว) — mirror _simulate_trade
    if m.partial_level is not None and not m.partial_done:
        partial_hit = high >= m.partial_level if sign > 0 else low <= m.partial_level
        if partial_hit:
            close_vol = round(m.lot * mgmt.partial_fraction, 2)
            result = broker.close_position(symbol, lt.open_ticket, volume=close_vol, expected_magic=lt.magic)
            if result.success:
                m.remaining_lot = round(m.remaining_lot - close_vol, 2)
                m.partial_done = True
                print(f"[live] {lt.team}:{lt.timeframe} partial TP {close_vol} lot @ {m.partial_level} "
                      f"เหลือ {m.remaining_lot} lot", flush=True)
                if mgmt.move_sl_to_breakeven:
                    m.current_sl = m.entry
                    broker.modify_sl_tp(symbol, lt.open_ticket, sl=m.current_sl, expected_magic=lt.magic)
            else:
                print(f"[live] {lt.team}:{lt.timeframe} partial TP ล้มเหลว: {result.message}", flush=True)

    # 4) trailing SL — mirror _simulate_trade (อัปเดตหลังเช็คทางออกทั้งหมดของแท่งนี้)
    if m.trail_dist is not None:
        m.extreme = max(m.extreme, high) if sign > 0 else min(m.extreme, low)
        reached_activation = (m.extreme - m.activate_level) * sign >= 0
        if reached_activation:
            was_active = m.trail_active
            m.trail_active = True
            candidate_sl = m.extreme - sign * m.trail_dist
            if (candidate_sl - m.current_sl) * sign > 0:
                m.current_sl = candidate_sl
                m.trail_moved = True
                new_tp = 0.0 if mgmt.remove_tp_when_trailing else None
                result = broker.modify_sl_tp(symbol, lt.open_ticket, sl=m.current_sl, tp=new_tp, expected_magic=lt.magic)
                if result.success:
                    tp_note = " (ลบ TP แล้ว — snowball โหมด)" if new_tp == 0.0 and not was_active else ""
                    print(f"[live] {lt.team}:{lt.timeframe} trailing SL เลื่อนไป {m.current_sl:.2f}{tp_note}",
                          flush=True)
                else:
                    print(f"[live] {lt.team}:{lt.timeframe} เลื่อน trailing SL ล้มเหลว: {result.message}",
                          flush=True)


def process_bar(
    broker: MT5Broker, lt: LiveTeam, symbol: str, cost: CostModel, dry_run: bool,
    discord_webhook_url: str | None = None, all_teams: list["LiveTeam"] | None = None,
) -> None:
    if lt.open_trade_id is not None:
        return  # v1: ทีมละ 1 ไม้พร้อมกัน (ไม่ pyramiding) — เช็ค open_trade_id ไม่ใช่ open_ticket
        # เพราะ dry_run ไม่มี ticket จริงจาก MT5 (เป็น None เสมอ) ถ้าเช็ค open_ticket ตรงนี้จะเปิดไม้ใหม่
        # ทับไม้เดิมทุกแท่งใหม่ในโหมด dry-run (ดู comment ใน run() ตรง dispatch loop)

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
        send_discord_alert(
            f"🛑 **Kill-switch ทำงาน** — `{lt.team}:{lt.timeframe}` หยุดเทรดถาวร\nเหตุผล: {gate.reason}\n"
            f"Balance ปัจจุบัน: ${lt.state.balance:.2f}",
            discord_webhook_url, level="critical",
            dedupe_key=f"killswitch_{lt.team}_{lt.timeframe}", dedupe_seconds=3600,
        )
        return
    if not gate.ok:
        return

    signal: Signal = lt.strategy.evaluate(data, idx)
    if not signal.is_actionable:
        return

    # กันชน conflict บนบัญชีเดียว: ถ้าทีมอื่นถือไม้ "สวนทาง" บน symbol เดียวกันอยู่ จะไม่เปิดไม้ใหม่
    # — บนบัญชี hedging สองไม้สวนกันคือจ่าย spread สองต่อเพื่อ net exposure ศูนย์ (เสียฟรี)
    # และการปิด/แก้ SL ของสองทีมอาจตีกันเอง จึงให้ไม้ที่เปิดก่อนมีสิทธิ์ก่อน (first-come-first-served)
    if all_teams is not None:
        opposite_holders = [
            t for t in all_teams
            if t is not lt and t.symbol == lt.symbol and t.open_trade_id is not None
            and t.open_entry_meta.get("direction") is not None
            and t.open_entry_meta["direction"] != signal.direction
        ]
        if opposite_holders:
            names = ", ".join(f"{t.team}:{t.timeframe}" for t in opposite_holders)
            print(f"[live] {lt.team}:{lt.timeframe} signal {signal.direction.value} แต่ {names} "
                  f"ถือไม้สวนทางบน {lt.symbol} อยู่ — ข้ามไม้นี้ (กัน conflict บนบัญชีเดียว)", flush=True)
            send_discord_alert(
                f"⚔️ **ข้ามไม้กัน conflict** — `{lt.team}:{lt.timeframe}` อยากเข้า {signal.direction.value} "
                f"{lt.symbol} แต่ {names} ถือไม้สวนทางอยู่ — ไม้เปิดก่อนได้สิทธิ์ก่อน",
                discord_webhook_url, level="warning",
                dedupe_key=f"conflict_{lt.team}_{lt.timeframe}", dedupe_seconds=1800,
            )
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

    result = broker.send_order(symbol, signal.direction, plan.lot, signal.sl, signal.tp, magic=lt.magic)
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
    margin_used = broker.calc_margin(symbol, signal.direction, plan.lot, signal.entry)
    lt.open_trade_id = lt.logger.log_trade_open(
        signal_id=signal_id, direction=signal.direction.value, entry_time=bar_time,
        entry=signal.entry, sl=signal.sl, tp=signal.tp, lot=plan.lot,
        ticket=result.ticket, margin_used=margin_used, regime=str(regime_series.iloc[idx]),
    )
    send_discord_alert(
        f"🔵 **เปิดไม้** — `{lt.team}:{lt.timeframe}` {signal.direction.value} {plan.lot} lot "
        f"@ {signal.entry:.2f}\nSL: {signal.sl:.2f} | TP: {signal.tp:.2f} | เหตุผล: {signal.reason}",
        discord_webhook_url, level="info", dedupe_key=None,
    )

    risk_dist = abs(signal.entry - signal.sl)
    mgmt = lt.management
    lt.manage_state = ManageState(
        direction=signal.direction, entry=signal.entry, original_sl=signal.sl, tp=signal.tp, lot=plan.lot,
        partial_level=(
            signal.entry + signal.direction.sign * risk_dist * mgmt.partial_tp_r
            if mgmt.partial_tp_r is not None else None
        ),
        trail_dist=(risk_dist * mgmt.trailing_stop_r if mgmt.trailing_stop_r is not None else None),
        activate_level=signal.entry + signal.direction.sign * risk_dist * mgmt.trailing_activate_r,
    )


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
    # dry-run กับ live ยิงเข้าคนละ webhook ตั้งใจ — กันข้อความเปิด/ปิดไม้ปนกันในช่องเดียว จนแยกไม่ออก
    # ว่าอันไหนเงินจริง (ดู DISCORD_WEBHOOK_URL_DRY_RUN ใน config.py/.env.example)
    webhook = settings.discord_webhook_url_dry_run if dry_run else settings.discord_webhook_url

    # roster entry: (team, tf) หรือ (team, tf, symbol) — ไม่ระบุ symbol = ใช้ settings.symbol
    # เปิดทางให้รันหลายสินทรัพย์บนบัญชีเดียว (เช่น GOLD + EURUSD) โดยแต่ละทีมผูกกับ symbol ของตัวเอง
    teams = [
        bootstrap_team(
            broker, entry[0], entry[1],
            entry[2] if len(entry) > 2 and entry[2] else settings.symbol,
            account_balance, settings.log_db_path, dry_run=dry_run,
        )
        for entry in roster
    ]
    print(f"[live] bootstrap เสร็จ {len(teams)} ทีม เริ่ม poll ทุก {poll_interval}s (Ctrl+C หยุด)", flush=True)

    # เช็ค orphan position: ไม้ที่เปิดจริงใน MT5 แต่ไม่มีทีมไหน claim (ticket ไม่ตรงกับของทีมไหนเลย)
    # เกิดได้ถ้า process ตายพอดีระหว่าง send_order() สำเร็จกับ log_trade_open() commit เสร็จ — ไม้แบบนี้
    # จะไม่มี record ใน DB เลยให้ find_open_trade() เจอตอน bootstrap จึงต้องสแกนเทียบกับ broker ตรงๆ
    if not dry_run:
        claimed_tickets = {lt.open_ticket for lt in teams if lt.open_ticket is not None}
        broker_positions = []
        for sym in {lt.symbol for lt in teams}:
            broker_positions.extend(broker.get_open_positions(sym))
        orphans = [p for p in broker_positions if p.ticket not in claimed_tickets]
        if orphans:
            orphan_desc = ", ".join(f"ticket={p.ticket} vol={p.volume}" for p in orphans)
            print(f"[live] คำเตือน: พบ {len(orphans)} orphan position ไม่มีทีมไหน claim — {orphan_desc}",
                  flush=True)
            send_discord_alert(
                f"🚨 **พบไม้กำพร้า (orphan position)** — {len(orphans)} ไม้ใน MT5 ไม่มี record ใน DB เลย: "
                f"{orphan_desc}\nน่าจะเกิดจาก process ตายระหว่างเปิดไม้ก่อน log ลง DB สำเร็จ — ตรวจสอบด้วยตนเอง",
                webhook, level="critical", dedupe_key=None,
            )

    send_discord_alert(
        f"🟢 **live_runner เริ่มทำงาน** — mode={'LIVE' if not dry_run else 'DRY-RUN'} "
        f"{len(teams)} ทีม balance=${account_balance:.2f}",
        webhook, level="info", dedupe_key=None,
    )

    cycle = 0
    try:
        while True:
            cycle += 1
            for lt in teams:
                try:
                    reconcile_open_position(broker, lt, dry_run, cost, discord_webhook_url=webhook)
                    if poll_new_bar(broker, lt, lt.symbol):
                        # open_trade_id (ไม่ใช่ open_ticket) คือตัวบ่งบอกว่า "มีไม้เปิดอยู่ไหม" ที่ถูกต้อง
                        # ทั้ง dry-run และ live — dry_run ไม่มี ticket จริงจาก MT5 (send_order คืน
                        # ticket=None เสมอ) ถ้าเช็ค open_ticket ตรงนี้ dry-run จะไม่รู้ตัวว่ามีไม้เปิดอยู่
                        # แล้วเข้า process_bar ซ้ำทุกแท่งใหม่ (เปิดไม้ใหม่ทับไม้เดิมที่ยังไม่ปิดใน DB ตลอดไป)
                        if lt.open_trade_id is not None:
                            manage_open_position(broker, lt, lt.symbol, dry_run)
                        else:
                            process_bar(broker, lt, lt.symbol, cost, dry_run,
                                        discord_webhook_url=webhook, all_teams=teams)
                    # อัปเดต heartbeat ทุกรอบ poll (ไม่ใช่แค่ตอนมีแท่งใหม่ปิด) — เพื่อให้ dashboard
                    # รู้ว่า process ยังมีชีวิตอยู่จริง แม้ timeframe ยาว (H1) ที่กว่าแท่งจะปิดใหม่นานเป็นชม.
                    lt.logger.update_heartbeat()
                    # บันทึก GateState ทุกรอบ poll ด้วย (ถูกๆ แค่ upsert แถวเดียว) กัน state หายตอน
                    # process ตาย/restart กะทันหัน — ดู bootstrap_team() ที่โหลดกลับตอน start
                    save_gate_state(settings.log_db_path, lt.team, lt.timeframe, lt.state)
                except NotDemoAccountError as exc:
                    send_discord_alert(
                        f"🚨 **CRITICAL: บัญชีไม่ใช่ demo** — {exc}\nระบบหยุดทำงานทันทีเพื่อความปลอดภัย",
                        webhook, level="critical", dedupe_key=None,
                    )
                    raise
                except Exception as exc:  # ทีมเดียวพังไม่ควรทำให้ทีมอื่นหยุด
                    print(f"[live] {lt.team}:{lt.timeframe} error: {exc}", flush=True)
                    send_discord_alert(
                        f"⚠️ **Error** — `{lt.team}:{lt.timeframe}`\n```{exc}```",
                        webhook, level="warning",
                        dedupe_key=f"error_{lt.team}_{lt.timeframe}", dedupe_seconds=1800,
                    )
            if cycle % 20 == 0:  # heartbeat กันสงสัยว่า process ตายไปหรือยัง (ทุก ~cycle*poll_interval วิ)
                print(
                    f"[live] heartbeat cycle={cycle} เวลา={datetime.now().strftime('%H:%M:%S')} "
                    f"ทีมที่ยังมีไม้เปิด={sum(1 for lt in teams if lt.open_ticket is not None)}/{len(teams)}",
                    flush=True,
                )
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        print("[live] หยุดตามคำสั่งผู้ใช้", flush=True)
        send_discord_alert("🟡 **live_runner หยุดทำงาน** (สั่งหยุดเอง — Ctrl+C)", webhook, level="warning", dedupe_key=None)
    except NotDemoAccountError:
        raise  # แจ้งเตือนไปแล้วในลูปด้านบน ไม่ต้องซ้ำ
    except Exception as exc:
        send_discord_alert(
            f"🔴 **live_runner ล่ม!** — process หยุดทำงานโดยไม่คาดคิด\n```{exc}```\n"
            f"ต้อง restart ด้วยตนเอง — ไม่มีการ auto-restart ในตัว process นี้",
            webhook, level="critical", dedupe_key=None,
        )
        raise
    finally:
        for lt in teams:
            lt.logger.close()
        broker.disconnect()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="ไม่ยิงออเดอร์จริง (ดีฟอลต์)")
    mode.add_argument("--live", action="store_true", help="ยิงออเดอร์เข้า MT5 demo จริง (ยังต้องเป็น demo)")
    p.add_argument("--teams", default=None,
                   help="เช่น trend_pullback:M30,london_breakout:M30:GOLD — รูปแบบ team:TF[:SYMBOL] "
                        "(ไม่ใส่ SYMBOL = ใช้ SYMBOL จาก .env, ว่างทั้งหมด=พอร์ตหลัก 8 ทีม)")
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

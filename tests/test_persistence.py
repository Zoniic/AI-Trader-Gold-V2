from datetime import date

from backtest.engine import Trade
from core.signal import Direction
from persistence.db import RunLogger, get_decisions, get_trades, list_runs, load_gate_state, save_gate_state
from risk.live_gate import GateState


def test_start_and_finish_run_round_trip(tmp_path):
    db_path = str(tmp_path / "log.db")
    logger = RunLogger(db_path, run_id="run_1")
    logger.start_run("ema_cross", initial_balance=10000.0)

    signal_id = logger.log_signal(
        bar_time="2024-01-01 00:00:00",
        strategy="ema_cross",
        direction="BUY",
        entry=1950.0,
        sl=1945.0,
        tp=1960.0,
        reason="test",
    )
    logger.log_decision(signal_id, approved=True, reason="ok", lot=0.1)
    trade = Trade(
        direction=Direction.BUY,
        entry_time="2024-01-01 00:00:00",
        entry=1950.0,
        sl=1945.0,
        tp=1960.0,
        lot=0.1,
        exit_time="2024-01-01 05:00:00",
        exit_price=1960.0,
        pnl=100.0,
        outcome="tp",
    )
    logger.log_trade(signal_id, trade)

    metrics = {
        "final_balance": 10100.0,
        "total_trades": 1,
        "win_rate_pct": 100.0,
        "profit_factor": float("inf"),
        "max_drawdown_pct": 0.0,
        "expectancy": 100.0,
    }
    logger.finish_run(metrics, halted_at=None, halt_reason="")
    logger.close()

    runs = list_runs(db_path)
    assert len(runs) == 1
    assert runs.iloc[0]["run_id"] == "run_1"
    assert runs.iloc[0]["total_trades"] == 1
    assert runs.iloc[0]["initial_balance"] == 10000.0

    trades = get_trades(db_path, "run_1")
    assert len(trades) == 1
    assert trades.iloc[0]["pnl"] == 100.0

    approved = get_decisions(db_path, "run_1", approved=True)
    rejected = get_decisions(db_path, "run_1", approved=False)
    assert len(approved) == 1
    assert len(rejected) == 0


def test_list_runs_on_empty_db_returns_empty_dataframe(tmp_path):
    db_path = str(tmp_path / "empty.db")
    runs = list_runs(db_path)  # ยังไม่เคยมี RunLogger เขียนอะไรเลย
    assert runs.empty


def test_gate_state_round_trip_survives_restart(tmp_path):
    """จำลอง process ตาย/restart — บันทึก GateState แล้วโหลดกลับ ต้องได้ peak_balance/probation
    /cooldown_events เหมือนเดิม (ยกเว้น cooldown_until ที่ต้องรีเซ็ตเป็น -1 เพราะ bar-index ไม่ portable
    ข้าม process — ดู comment ใน execution/live_runner.py::bootstrap_team)
    """
    db_path = str(tmp_path / "gate.db")
    state = GateState(balance=9500.0)
    state.peak_balance = 10500.0
    state.current_date = date(2026, 7, 10)
    state.current_week = (2026, 28)
    state.day_start_balance = 9800.0
    state.week_start_balance = 10000.0
    state.cooldown_until = 850  # ค่านี้ไม่ portable — คาดว่าจะหายหลังโหลดกลับ
    state.in_probation = True
    state.probation_events = 3

    save_gate_state(db_path, "trend_pullback", "M30", state)
    loaded = load_gate_state(db_path, "trend_pullback", "M30")

    assert loaded is not None
    assert loaded.peak_balance == 10500.0
    assert loaded.current_date == date(2026, 7, 10)
    assert loaded.current_week == (2026, 28)
    assert loaded.day_start_balance == 9800.0
    assert loaded.week_start_balance == 10000.0
    assert loaded.in_probation is True
    assert loaded.probation_events == 3

    # ทีมที่ไม่เคยบันทึกมาก่อน (ทีมใหม่) ต้องได้ None ไม่ใช่ throw
    assert load_gate_state(db_path, "never_seen_team", "H1") is None

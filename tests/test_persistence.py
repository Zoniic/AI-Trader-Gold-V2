from backtest.engine import Trade
from core.signal import Direction
from persistence.db import RunLogger, get_decisions, get_trades, list_runs


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

from backtest.engine import Trade
from backtest.regime_league import compute_regime_league
from core.signal import Direction
from persistence.db import RunLogger


def _log_run(db_path: str, run_id: str, strategy: str, timeframe: str, trades_spec):
    """trades_spec: list ของ (regime, pnl)"""
    logger = RunLogger(db_path, run_id=run_id)
    logger.start_run(strategy, 10000.0, timeframe=timeframe, config="{}")
    for i, (regime, pnl) in enumerate(trades_spec):
        sig_id = logger.log_signal(f"2024-01-01 {i % 24:02d}:00:00", strategy, "BUY",
                                   2000.0, 1990.0, 2020.0, "t")
        trade = Trade(
            direction=Direction.BUY, entry_time="2024-01-01", entry=2000.0, sl=1990.0,
            tp=2020.0, lot=0.1, exit_time="2024-01-01", exit_price=2000.0 + pnl / 10,
            pnl=pnl, outcome="tp" if pnl > 0 else "sl", regime=regime,
            pnl_r=pnl / 100, mae_r=0.2, mfe_r=1.0, review="",
        )
        logger.log_trade(sig_id, trade)
    logger.finish_run({"final_balance": 10000, "total_trades": len(trades_spec),
                       "win_rate_pct": 50, "profit_factor": 1, "max_drawdown_pct": -5,
                       "expectancy": 0})
    logger.close()


def test_champion_per_regime_with_min_trades_guard(tmp_path):
    db = str(tmp_path / "league.db")
    # ทีม A เก่ง trend (20 ไม้กำไร) / ทีม B เก่ง range (20 ไม้กำไรมากกว่า A ใน range)
    _log_run(db, "run_a", "team_a", "H1",
             [("trend", 50)] * 20 + [("range", -10)] * 20)
    _log_run(db, "run_b", "team_b", "H1",
             [("trend", -20)] * 20 + [("range", 30)] * 20 + [("volatile", 5)] * 3)

    result = compute_regime_league(db, min_trades=15)
    champs = {(c["timeframe"], c["regime"]): c for c in result["champions"]}

    assert champs[("H1", "trend")]["champion"] == "team_a"
    assert champs[("H1", "range")]["champion"] == "team_b"
    # volatile มีแค่ 3 ไม้ (< 15) — ต้องไม่มีแชมป์
    assert champs[("H1", "volatile")]["champion"] is None


def test_latest_run_wins_over_older_run(tmp_path):
    db = str(tmp_path / "league2.db")
    _log_run(db, "run_old", "team_a", "H1", [("trend", -50)] * 20)
    _log_run(db, "run_new", "team_a", "H1", [("trend", 40)] * 20)  # ใหม่กว่า (insert ทีหลัง)

    result = compute_regime_league(db, min_trades=15)
    champ = next(c for c in result["champions"] if c["regime"] == "trend")
    # ต้องใช้ผลจาก run ล่าสุด (กำไร) ไม่ใช่ run เก่า
    assert champ["champion"] == "team_a"
    assert champ["total_pnl"] == 800.0

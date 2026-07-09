import sqlite3

import pandas as pd

from backtest.costs import CostModel
from backtest.engine import run_backtest
from core.signal import MarketData
from persistence.db import RunLogger
from risk.position_sizing import RiskConfig
from strategies.ema_cross import EMACrossStrategy
from tests.helpers import make_synthetic_df


def test_strategy_ignores_future_bars():
    """หัวใจของการกัน lookahead bias: เปลี่ยนอนาคตแล้วสัญญาณที่ประเมิน ณ ปัจจุบันต้องไม่เปลี่ยน"""
    common_len = 200
    df_a = make_synthetic_df(common_len + 10, seed=1)
    df_b = df_a.copy()
    for col in ("open", "high", "low", "close"):
        df_b.iloc[common_len:, df_b.columns.get_loc(col)] += 100  # อนาคตต่างกันมาก

    strategy = EMACrossStrategy()
    eval_idx = common_len - 1

    sig_a = strategy.evaluate(MarketData(df=df_a), eval_idx)
    sig_b = strategy.evaluate(MarketData(df=df_b), eval_idx)

    assert sig_a.direction == sig_b.direction
    assert sig_a.entry == sig_b.entry
    assert sig_a.sl == sig_b.sl
    assert sig_a.tp == sig_b.tp


def test_engine_logs_every_signal_decision_and_trade(tmp_path):
    df = make_synthetic_df(1500, seed=7)
    data = MarketData(df=df)
    strategy = EMACrossStrategy()
    risk_cfg = RiskConfig(account_balance=10000, risk_per_trade_pct=1.0)
    cost = CostModel(spread_points=30, slippage_points=5)

    db_path = str(tmp_path / "test_log.db")
    logger = RunLogger(db_path, run_id="test_run")

    result = run_backtest(strategy, data, risk_cfg, cost, logger=logger)
    logger.close()

    conn = sqlite3.connect(db_path)
    signal_count = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    decision_count = conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
    trade_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    conn.close()

    assert signal_count > 0  # กลยุทธ์ควรยิงสัญญาณอย่างน้อยหนึ่งครั้งใน 1500 แท่ง
    assert decision_count == signal_count  # ทุก signal ต้องมี decision ตามมาเสมอ (อนุมัติหรือไม่ก็ตาม)
    assert trade_count == len(result.trades)
    assert trade_count <= signal_count  # เทรดจริงต้อง <= สัญญาณ (บาง signal ถูกปฏิเสธโดย risk guard)

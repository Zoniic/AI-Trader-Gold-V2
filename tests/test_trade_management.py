"""เทสต์กลไก trade management + MAE/MFE ด้วยเส้นทางราคาที่กำหนดเองแบบ deterministic"""
from types import SimpleNamespace

import pandas as pd

from backtest.engine import TradeManagement, _post_exit_run, _simulate_trade
from backtest.review import aggregate_review, review_trade
from core.signal import Direction
from persistence.db import RunLogger, list_runs


def _df(bars: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(bars), freq="h")
    return pd.DataFrame(
        [{"open": o, "high": h, "low": low, "close": c, "volume": 100} for o, h, low, c in bars],
        index=idx,
    )


# BUY: entry=100, SL=98 (risk 2), TP=106 (3R), partial ที่ 1R = 102


def test_partial_tp_then_breakeven_exit():
    df = _df([
        (100, 101.0, 99.5, 100.5),   # ยังไม่ถึงอะไร (mae 0.5)
        (100.5, 102.5, 100.5, 102),  # ชน partial 102 → SL เลื่อนไป 100 (BE)
        (102, 103.0, 100.0, 100.2),  # low 100 ชน BE
    ])
    mgmt = TradeManagement(partial_tp_r=1.0, partial_fraction=0.5, move_sl_to_breakeven=True)
    exit_idx, parts, outcome, mae_r, mfe_r = _simulate_trade(
        df, 0, Direction.BUY, 100.0, 98.0, 106.0, 50, mgmt
    )
    assert outcome == "be_after_partial"
    assert exit_idx == 2
    assert parts == [(0.5, 102.0), (0.5, 100.0)]
    assert mae_r == 0.25  # ลึกสุด 0.5 จาก risk 2
    assert mfe_r == 1.5   # สูงสุด 103 = +3 จาก risk 2


def test_no_management_same_path_times_out():
    df = _df([
        (100, 101.0, 99.5, 100.5),
        (100.5, 102.5, 100.5, 102),
        (102, 103.0, 100.0, 100.2),
    ])
    exit_idx, parts, outcome, _, _ = _simulate_trade(
        df, 0, Direction.BUY, 100.0, 98.0, 106.0, 50, TradeManagement()
    )
    assert outcome == "end_of_data"
    assert parts == [(1.0, 100.2)]


def test_sl_checked_before_tp_in_ambiguous_bar():
    df = _df([(100, 106.5, 97.5, 100)])  # แท่งเดียวแตะทั้ง SL และ TP
    _, parts, outcome, _, _ = _simulate_trade(
        df, 0, Direction.BUY, 100.0, 98.0, 106.0, 50, TradeManagement()
    )
    assert outcome == "sl"
    assert parts == [(1.0, 98.0)]


def test_full_tp_after_partial():
    df = _df([
        (100, 102.5, 99.8, 102),   # partial ที่ 102
        (102, 106.5, 101.5, 106),  # TP 106
    ])
    mgmt = TradeManagement(partial_tp_r=1.0)
    _, parts, outcome, _, _ = _simulate_trade(
        df, 0, Direction.BUY, 100.0, 98.0, 106.0, 50, mgmt
    )
    assert outcome == "tp_after_partial"
    assert parts == [(0.5, 102.0), (0.5, 106.0)]


def test_post_exit_run_measures_continuation():
    df = _df([
        (100, 106.5, 99.9, 106),  # exit ที่ TP idx 0
        (106, 108.0, 105.5, 107),
        (107, 109.0, 106.5, 108),  # วิ่งต่อสูงสุด 109 = +3 เหนือ TP = 1.5R (risk 2)
    ])
    r = _post_exit_run(df, 0, Direction.BUY, 106.0, 2.0)
    assert r == 1.5


def test_review_trade_flags_partial_tp_opportunity():
    text = review_trade("sl", -1.02, 1.0, 1.4, None)
    assert "partial" in text.lower() or "BE" in text


def test_aggregate_review_recommends_partial_when_losses_were_winning():
    def fake(pnl, pnl_r, mae_r, mfe_r, outcome, post_exit_r=None):
        return SimpleNamespace(pnl=pnl, pnl_r=pnl_r, mae_r=mae_r, mfe_r=mfe_r,
                               outcome=outcome, post_exit_r=post_exit_r)

    trades = [fake(-100, -1.0, 1.0, 1.3, "sl") for _ in range(4)] + [
        fake(200, 2.0, 0.2, 2.0, "tp", post_exit_r=0.1) for _ in range(2)
    ]
    summary = aggregate_review(trades)
    assert summary["losses_were_winning_1r"] == 4
    assert any("partial" in r.lower() for r in summary["recommendations"])


def test_run_config_snapshot_round_trip(tmp_path):
    db_path = str(tmp_path / "cfg.db")
    logger = RunLogger(db_path, run_id="cfg_run")
    logger.start_run("ema_cross", 10000.0, timeframe="M15", config='{"k": 1}')
    logger.close()

    runs = list_runs(db_path)
    assert runs.iloc[0]["timeframe"] == "M15"
    assert runs.iloc[0]["config"] == '{"k": 1}'

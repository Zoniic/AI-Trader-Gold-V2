"""Contract test กลางสำหรับทุกทีม — ทีมใหม่ที่ลงทะเบียนใน registry จะถูกเทสต์อัตโนมัติ"""
import json
import sqlite3

import numpy as np
import pandas as pd
import pytest

import strategies  # noqa: F401  เติม registry
from core.signal import Direction, MarketData, Signal
from core.strategy import STRATEGY_REGISTRY
from tests.helpers import make_synthetic_df


def _mixed_market_df(n: int = 1200, seed: int = 11) -> pd.DataFrame:
    """ข้อมูลสังเคราะห์ที่มีทั้งช่วงเทรนด์/แกว่ง/ผันผวน เพื่อให้ทุกทีมมีโอกาสเจอ setup ของตัวเอง"""
    rng = np.random.default_rng(seed)
    parts = [
        np.cumsum(rng.normal(0.25, 0.4, size=n // 3)),          # เทรนด์ขึ้น
        3 * np.sin(np.arange(n // 3) / 5) + rng.normal(0, 0.3, size=n // 3),  # แกว่งกรอบ
        np.cumsum(rng.normal(-0.2, 0.8, size=n - 2 * (n // 3))),  # เทรนด์ลงผันผวน
    ]
    base = 1950.0 + np.concatenate([parts[0], parts[0][-1] + parts[1], parts[0][-1] + parts[1][-1] + parts[2]])
    idx = pd.date_range("2024-01-02", periods=n, freq="h")
    high = base + np.abs(rng.normal(0.4, 0.25, size=n))
    low = base - np.abs(rng.normal(0.4, 0.25, size=n))
    return pd.DataFrame(
        {"open": base + rng.normal(0, 0.1, size=n), "high": high, "low": low, "close": base,
         "volume": rng.integers(50, 500, size=n)},
        index=idx,
    )


ALL_TEAMS = sorted(STRATEGY_REGISTRY.keys())


def test_registry_has_all_15_teams():
    assert len(STRATEGY_REGISTRY) == 15


@pytest.mark.parametrize("team", ALL_TEAMS)
def test_team_has_5_member_committee(team):
    inst = STRATEGY_REGISTRY[team]()
    members = inst.committee_info()
    assert len(members) == 5
    assert all(m["name"] and m["role"] for m in members)


@pytest.mark.parametrize("team", ALL_TEAMS)
def test_team_returns_valid_signals_over_mixed_market(team):
    df = _mixed_market_df()
    data = MarketData(df=df)
    inst = STRATEGY_REGISTRY[team]()
    start = inst.min_lookback()

    actionable = 0
    for i in range(start, len(df)):
        sig = inst.evaluate(data, i)
        assert isinstance(sig, Signal)
        if sig.is_actionable:
            actionable += 1
            # SL/TP ต้องอยู่ถูกฝั่งของราคาเข้าเสมอ
            if sig.direction == Direction.BUY:
                assert sig.sl < sig.entry < sig.tp, f"{team}: BUY แต่ SL/TP ผิดฝั่ง"
            else:
                assert sig.tp < sig.entry < sig.sl, f"{team}: SELL แต่ SL/TP ผิดฝั่ง"
            # ทุกไม้ที่อนุมัติต้องมีความเห็นครบ 5 คน
            discussion = sig.meta.get("discussion")
            assert discussion is not None and len(discussion) == 5, f"{team}: ไม่มีความเห็นครบ 5 คน"
            dissents = sum(1 for o in discussion if not o["approve"])
            assert dissents <= 1, f"{team}: อนุมัติทั้งที่มีเสียงค้าน {dissents}"
    # ไม่บังคับว่าทุกทีมต้องมีไม้ (บางทีมเลือกมาก) แต่ห้าม crash — บันทึกไว้เฉยๆ
    print(f"{team}: actionable={actionable}")


@pytest.mark.parametrize("team", ALL_TEAMS)
def test_team_ignores_future_bars(team):
    inst = STRATEGY_REGISTRY[team]()
    cutoff = inst.min_lookback() + 150
    df_a = _mixed_market_df(n=cutoff + 60, seed=23)
    df_b = df_a.copy()
    for col in ("open", "high", "low", "close"):
        df_b.iloc[cutoff:, df_b.columns.get_loc(col)] += 300  # อนาคตต่างกันมาก

    # เทียบหลายจุดก่อน cutoff — สัญญาณต้องเหมือนกันเป๊ะแม้อนาคตต่าง
    for eval_idx in range(cutoff - 20, cutoff):
        sig_a = inst.evaluate(MarketData(df=df_a), eval_idx)
        sig_b = inst.evaluate(MarketData(df=df_b), eval_idx)
        assert sig_a.direction == sig_b.direction, f"{team}: lookahead ที่ idx={eval_idx}"
        assert sig_a.entry == sig_b.entry
        assert sig_a.sl == sig_b.sl
        assert sig_a.tp == sig_b.tp


def test_discussion_round_trip_to_db(tmp_path):
    """ความเห็นคณะกรรมการต้องถูกบันทึกลง DB และ JOIN กลับมากับเทรดได้ครบ 5 คน"""
    from backtest.costs import CostModel
    from backtest.engine import run_backtest
    from persistence.db import RunLogger, get_trades
    from risk.position_sizing import RiskConfig

    df = _mixed_market_df(n=1500, seed=7)
    data = MarketData(df=df)
    strategy = STRATEGY_REGISTRY["ema_cross"]()
    db_path = str(tmp_path / "disc.db")
    logger = RunLogger(db_path, run_id="disc_test")

    result = run_backtest(strategy, data, RiskConfig(), CostModel(), logger=logger)
    logger.close()
    assert len(result.trades) > 0, "ต้องมีเทรดอย่างน้อย 1 ไม้ให้ตรวจ"

    trades_df = get_trades(db_path, "disc_test")
    assert "discussion" in trades_df.columns
    first_discussion = trades_df["discussion"].iloc[0]
    assert first_discussion is not None
    parsed = json.loads(first_discussion)
    assert len(parsed) == 5
    assert all({"member", "role", "approve", "comment"} <= set(o.keys()) for o in parsed)

"""เทสต์ regime gate (จำกัดทีมเทรดเฉพาะสภาวะที่ถนัด) + การปรับ min_approvals"""
import pandas as pd
import pytest

import backtest.engine as engine_module
from backtest.costs import CostModel
from backtest.engine import run_backtest
from core.committee import Committee, CommitteeMember
from core.signal import Direction, MarketData, Signal
from core.strategy import Strategy
from risk.position_sizing import RiskConfig
from tests.helpers import make_synthetic_df


class AlwaysBuyStrategy(Strategy):
    """ยิง BUY ทุกแท่ง — ไว้เทสต์ engine gate ล้วนๆ ไม่เกี่ยวกับ logic กลยุทธ์"""

    name = "always_buy_test"

    def min_lookback(self) -> int:
        return 5

    def evaluate(self, data: MarketData, idx: int) -> Signal:
        close = float(data.df["close"].iloc[idx])
        return Signal(direction=Direction.BUY, entry=close, sl=close - 2.0, tp=close + 4.0)


def test_regime_gate_blocks_disallowed_bars(monkeypatch):
    df = make_synthetic_df(300, seed=9)
    # ครึ่งแรก trend ครึ่งหลัง range — จะดูว่า gate ตัดครึ่งแรกออกจริง
    fake_regime = pd.Series(
        ["trend"] * 150 + ["range"] * 150, index=df.index
    )
    monkeypatch.setattr(engine_module, "compute_regime", lambda _df: fake_regime)

    result_all = run_backtest(
        AlwaysBuyStrategy(), MarketData(df=df), RiskConfig(max_drawdown_pct=99.0),
        CostModel(spread_points=0, slippage_points=0),
    )
    result_gated = run_backtest(
        AlwaysBuyStrategy(), MarketData(df=df), RiskConfig(max_drawdown_pct=99.0),
        CostModel(spread_points=0, slippage_points=0),
        allowed_regimes=["range"],
    )

    assert len(result_gated.trades) < len(result_all.trades)
    assert all(t.regime == "range" for t in result_gated.trades)
    assert any(t.regime == "trend" for t in result_all.trades)


def test_min_approvals_5_rejects_single_dissent():
    def approve(ctx):
        return True, "ok"

    def dissent(ctx):
        return False, "no"

    members = [CommitteeMember(f"m{i}", "T", approve) for i in range(4)] + [
        CommitteeMember("ค้าน", "T", dissent)
    ]
    committee = Committee(members, min_approvals=4)
    approved_at_4, _ = committee.review({})
    committee.min_approvals = 5  # แบบที่ run_backtest ปรับจาก config
    approved_at_5, _ = committee.review({})

    assert approved_at_4 is True
    assert approved_at_5 is False

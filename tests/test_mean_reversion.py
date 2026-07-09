import numpy as np
import pandas as pd

from core.signal import Direction, MarketData
from strategies.mean_reversion import MeanReversionStrategy


def _make_oscillating_df(n=200, seed=1) -> pd.DataFrame:
    x = np.arange(n)
    rng = np.random.default_rng(seed)
    close = 1950.0 + 15 * np.sin(x / 10) + rng.normal(0, 0.3, size=n)
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "volume": 100,
        },
        index=idx,
    )


def test_flat_data_produces_no_signal():
    """ราคานิ่งสนิท ไม่มีทางหลุดกรอบ Bollinger ได้ -> ต้องไม่มีสัญญาณ"""
    n = 100
    close = np.full(n, 1950.0)
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    df = pd.DataFrame(
        {"open": close, "high": close + 0.1, "low": close - 0.1, "close": close, "volume": 100},
        index=idx,
    )
    strategy = MeanReversionStrategy()
    for i in range(strategy.min_lookback(), n):
        sig = strategy.evaluate(MarketData(df=df), i)
        assert not sig.is_actionable


def test_oscillating_data_eventually_produces_valid_signal():
    df = _make_oscillating_df()
    strategy = MeanReversionStrategy()

    signals = [
        strategy.evaluate(MarketData(df=df), i)
        for i in range(strategy.min_lookback(), len(df))
    ]
    actionable = [s for s in signals if s.is_actionable]

    assert len(actionable) > 0
    for sig in actionable:
        assert sig.direction in (Direction.BUY, Direction.SELL)
        assert sig.sl is not None and sig.tp is not None
        # เป้าหมาย mean reversion ต้องอยู่ "ใกล้เส้นกลาง" มากกว่าฝั่ง SL เสมอ
        if sig.direction == Direction.BUY:
            assert sig.tp > sig.entry > sig.sl
        else:
            assert sig.tp < sig.entry < sig.sl


def test_strategy_ignores_future_bars():
    common_len = 150
    df_a = _make_oscillating_df(n=common_len + 10, seed=5)
    df_b = df_a.copy()
    for col in ("open", "high", "low", "close"):
        df_b.iloc[common_len:, df_b.columns.get_loc(col)] += 100

    strategy = MeanReversionStrategy()
    eval_idx = common_len - 1

    sig_a = strategy.evaluate(MarketData(df=df_a), eval_idx)
    sig_b = strategy.evaluate(MarketData(df=df_b), eval_idx)

    assert sig_a.direction == sig_b.direction
    assert sig_a.entry == sig_b.entry
    assert sig_a.sl == sig_b.sl
    assert sig_a.tp == sig_b.tp

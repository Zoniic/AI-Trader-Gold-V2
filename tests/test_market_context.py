"""เทสต์ core/market_context.py — pre-trade checklist (เฉพาะข้อที่คำนวณได้จริง)"""
import numpy as np
import pandas as pd

from core.market_context import compute_pre_trade_context, context_to_dict
from core.signal import Direction


def _uptrend_df(n=300):
    idx = pd.date_range("2024-01-01 10:00", periods=n, freq="h")
    base = 2000 + np.cumsum(np.full(n, 0.5)) + np.sin(np.arange(n) / 6) * 3
    return pd.DataFrame(
        {"open": base, "high": base + 1.0, "low": base - 1.0, "close": base,
         "volume": np.full(n, 100.0)},
        index=idx,
    )


def test_context_computes_core_fields():
    df = _uptrend_df()
    ctx = compute_pre_trade_context(
        df, Direction.BUY, entry=float(df["close"].iloc[-1]),
        sl=float(df["close"].iloc[-1]) - 5, tp=float(df["close"].iloc[-1]) + 15,
        atr=2.0, atr_median=2.0,
    )
    assert ctx.trend in ("up", "down", "sideway")
    assert ctx.rr > 0
    assert ctx.session in ("asia", "london", "overlap", "ny", "off")
    assert 0 <= ctx.quality_score <= 100


def test_poor_rr_is_flagged_skip():
    df = _uptrend_df()
    price = float(df["close"].iloc[-1])
    ctx = compute_pre_trade_context(
        df, Direction.BUY, entry=price, sl=price - 10, tp=price + 3,  # RR 0.3
        atr=2.0, atr_median=2.0, min_rr=1.3,
    )
    assert ctx.reward_quality == "poor"
    assert ctx.skip_recommended is True


def test_overextended_is_flagged():
    df = _uptrend_df()
    price = float(df["close"].iloc[-1]) + 50  # ไกลจาก EMA50 มาก
    ctx = compute_pre_trade_context(
        df, Direction.BUY, entry=price, sl=price - 5, tp=price + 15,
        atr=2.0, atr_median=2.0, overext_atr_threshold=3.0,
    )
    assert ctx.gold_overextended is True
    assert ctx.skip_recommended is True


def test_external_fields_are_none_not_faked():
    df = _uptrend_df()
    price = float(df["close"].iloc[-1])
    ctx = compute_pre_trade_context(
        df, Direction.BUY, entry=price, sl=price - 5, tp=price + 15, atr=2.0, atr_median=2.0
    )
    # ข้อที่ต้องมี data ภายนอกต้องเป็น None เสมอ — ไม่เดามั่ว
    assert ctx.dxy_corr is None
    assert ctx.us10y_corr is None
    assert ctx.news_minutes is None
    assert ctx.order_block is None
    assert ctx.fair_value_gap is None


def test_context_to_dict_lists_unavailable_externals():
    df = _uptrend_df()
    price = float(df["close"].iloc[-1])
    ctx = compute_pre_trade_context(
        df, Direction.BUY, entry=price, sl=price - 5, tp=price + 15, atr=2.0, atr_median=2.0
    )
    d = context_to_dict(ctx)
    assert "dxy_corr" in d["pt_external_unavailable"]
    assert "news_minutes" in d["pt_external_unavailable"]
    assert d["pt_rr"] > 0

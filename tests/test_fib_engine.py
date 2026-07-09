"""เทสต์ core/fib_engine.py — swing detection, fib levels, price action patterns"""
import pandas as pd

from core.fib_engine import (
    active_leg,
    classify_trend,
    detect_swings,
    fib_extension_levels,
    fib_retracement_levels,
    fib_zone_hit,
    is_bearish_engulfing,
    is_bullish_engulfing,
    is_pin_bar,
    price_action_confirmation,
)


def _make_df(closes):
    n = len(closes)
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [100] * n,
        },
        index=idx,
    )


def test_detect_swings_finds_obvious_peak_and_trough():
    # V shape: ลงแล้วขึ้น -> ต้องเจอ low ตรงกลาง
    closes = [10, 9, 8, 7, 6, 7, 8, 9, 10, 11]
    df = _make_df(closes)
    swings = detect_swings(df, order=3)
    lows = [s for s in swings if s.kind == "low"]
    assert any(s.price == 6 - 0.5 for s in lows)  # low = close-0.5 ตาม _make_df


def test_classify_trend_up_needs_higher_high_and_higher_low():
    from core.fib_engine import Swing

    swings = [
        Swing(0, 100, "low"), Swing(1, 110, "high"),
        Swing(2, 105, "low"), Swing(3, 120, "high"),
    ]
    assert classify_trend(swings) == "up"


def test_classify_trend_down_needs_lower_high_and_lower_low():
    from core.fib_engine import Swing

    swings = [
        Swing(0, 120, "high"), Swing(1, 100, "low"),
        Swing(2, 110, "high"), Swing(3, 90, "low"),
    ]
    assert classify_trend(swings) == "down"


def test_classify_trend_sideway_when_mixed():
    from core.fib_engine import Swing

    # higher high แต่ lower low (กรอบขยาย ไม่ใช่เทรนด์ชัด) -> ไม่เข้าเงื่อนไข up หรือ down เลย
    swings = [
        Swing(0, 100, "low"), Swing(1, 110, "high"),
        Swing(2, 90, "low"), Swing(3, 120, "high"),
    ]
    assert classify_trend(swings) == "sideway"


def test_active_leg_uptrend_picks_low_before_last_high():
    from core.fib_engine import Swing

    swings = [
        Swing(0, 100, "low"), Swing(2, 110, "high"),
        Swing(4, 105, "low"), Swing(6, 120, "high"),
    ]
    leg = active_leg(swings, "up")
    assert leg is not None
    lo, hi = leg
    assert lo.price == 105 and hi.price == 120


def test_fib_retracement_levels_uptrend_between_low_and_high():
    levels = fib_retracement_levels(100.0, 200.0, "up")
    assert levels[0.618] == 200.0 - 100.0 * 0.618
    assert all(100.0 < v < 200.0 for v in levels.values())


def test_fib_retracement_levels_downtrend_between_low_and_high():
    levels = fib_retracement_levels(100.0, 200.0, "down")
    assert levels[0.618] == 100.0 + 100.0 * 0.618
    assert all(100.0 < v < 200.0 for v in levels.values())


def test_fib_extension_levels_uptrend_go_beyond_swing_high():
    ext = fib_extension_levels(100.0, 200.0, "up")
    assert ext[1.618] > 200.0
    assert ext[2.618] > ext[1.618] > ext[1.272]


def test_fib_extension_levels_downtrend_go_beyond_swing_low():
    ext = fib_extension_levels(100.0, 200.0, "down")
    assert ext[1.618] < 100.0
    assert ext[2.618] < ext[1.618] < ext[1.272]


def test_fib_zone_hit_prefers_highest_weight_when_overlapping():
    # 61.8% ให้น้ำหนักสูงสุด — ถ้าราคาอยู่ในโซนที่ทับกันหลายระดับ ต้องเลือกอันนี้
    levels = {0.5: 100.0, 0.618: 100.5}
    hit = fib_zone_hit(100.2, levels, zone_width=1.0)
    assert hit is not None
    assert hit[0] == 0.618


def test_fib_zone_hit_none_when_far_from_all_levels():
    levels = {0.5: 100.0, 0.618: 110.0}
    assert fib_zone_hit(50.0, levels, zone_width=1.0) is None


def test_bullish_engulfing_detected():
    df = pd.DataFrame(
        {"open": [10, 8], "close": [9, 11], "high": [10.2, 11.2], "low": [8.8, 7.8]}
    )
    assert is_bullish_engulfing(df, 1) == True
    assert is_bearish_engulfing(df, 1) == False


def test_bearish_engulfing_detected():
    df = pd.DataFrame(
        {"open": [9, 11], "close": [10, 8], "high": [10.2, 11.2], "low": [8.8, 7.8]}
    )
    assert is_bearish_engulfing(df, 1) == True
    assert is_bullish_engulfing(df, 1) == False


def test_pin_bar_hammer_for_buy():
    df = pd.DataFrame({"open": [9.9], "close": [10.0], "high": [10.1], "low": [8.0]})
    assert is_pin_bar(df, 0, direction_sign=1) == True
    assert is_pin_bar(df, 0, direction_sign=-1) == False


def test_price_action_confirmation_requires_touch_and_pattern():
    closes = [100, 99, 98, 97, 96]
    df = pd.DataFrame(
        {
            "open": [100, 99, 98, 97, 95.5],
            "close": [99, 98, 97, 96, 98],  # แท่งสุดท้าย engulf ขึ้นแรง
            "high": [100.5, 99.5, 98.5, 97.5, 98.2],
            "low": [98.5, 97.5, 96.5, 95.5, 95.3],
        }
    )
    confirmed, pattern, bars_ago = price_action_confirmation(
        df, direction_sign=1, zone_low=95.0, zone_high=97.0, max_bars=3
    )
    assert confirmed is True
    assert pattern in ("bullish_engulfing", "hammer")

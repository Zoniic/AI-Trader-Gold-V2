import numpy as np
import pandas as pd

from backtest.regime import _apply_hysteresis, compute_regime


def _make_df(close: np.ndarray, high_pad: float = 0.3, low_pad: float = 0.3) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(close), freq="h")
    return pd.DataFrame(
        {
            "open": close,
            "high": close + high_pad,
            "low": close - low_pad,
            "close": close,
            "volume": 100,
        },
        index=idx,
    )


def test_strong_uptrend_is_mostly_classified_trend():
    rng = np.random.default_rng(1)
    steps = rng.normal(0.3, 0.05, size=300)  # ทิศทางเดียวชัดเจน noise น้อย
    close = 1950.0 + np.cumsum(steps)
    df = _make_df(close)

    regime = compute_regime(df)
    tail = regime.iloc[100:]  # ตัด warmup ออก
    trend_ratio = (tail == "trend").mean()

    assert trend_ratio > 0.5


def test_choppy_sideways_is_not_mostly_trend():
    # sin(x) รอบสั้นมาก (~6 แท่ง/รอบ) ทำให้ทิศทางกลับตัวถี่กว่า ADX(14) window เสมอ
    # ต่างจาก sin(x/8) (~50 แท่ง/รอบ) ซึ่งดูเป็นเทรนด์จริงในกรอบสั้นได้ (ADX ตรวจถูกแล้ว)
    x = np.arange(300)
    rng = np.random.default_rng(2)
    close = 1950.0 + 3 * np.sin(x) + rng.normal(0, 0.2, size=300)
    df = _make_df(close)

    regime = compute_regime(df)
    tail = regime.iloc[100:]
    trend_ratio = (tail == "trend").mean()

    assert trend_ratio < 0.4


def test_sudden_spike_gets_flagged_volatile():
    rng = np.random.default_rng(3)
    steps = rng.normal(0, 0.15, size=300)  # ความผันผวนต่ำสม่ำเสมอเป็น baseline
    close = 1950.0 + np.cumsum(steps)
    df = _make_df(close)

    spike_idx = 250
    # ทำให้แท่งนี้มี true range ใหญ่ผิดปกติ (จำลองข่าวแรง) โดยไม่แตะ index ก่อนหน้า
    df.iloc[spike_idx, df.columns.get_loc("high")] = df["close"].iloc[spike_idx] + 30
    df.iloc[spike_idx, df.columns.get_loc("low")] = df["close"].iloc[spike_idx] - 30

    regime = compute_regime(df)

    assert regime.iloc[spike_idx] == "volatile"


def test_regime_uses_only_past_data_no_lookahead():
    rng = np.random.default_rng(4)
    steps = rng.normal(0, 0.3, size=300)
    close_a = 1950.0 + np.cumsum(steps)
    df_a = _make_df(close_a)
    df_b = df_a.copy()

    cutoff = 200
    for col in ("open", "high", "low", "close"):
        df_b.iloc[cutoff:, df_b.columns.get_loc(col)] += 500  # อนาคตต่างกันมาก

    regime_a = compute_regime(df_a)
    regime_b = compute_regime(df_b)

    # regime ที่ index ก่อน cutoff ต้องเหมือนกันทุกจุด แม้อนาคตจะต่างกันโดยสิ้นเชิง
    assert (regime_a.iloc[:cutoff] == regime_b.iloc[:cutoff]).all()


def test_hysteresis_confirm_bars_1_is_unchanged_behavior():
    """confirm_bars=1 (ค่าเริ่มต้น) ต้องให้ผลเหมือนไม่มี hysteresis เลย (backward compat)"""
    raw = pd.Series(["range", "trend", "range", "trend", "trend", "volatile"])
    result = _apply_hysteresis(raw, confirm_bars=1)
    assert (result == raw).all()


def test_hysteresis_blocks_single_bar_flip_flop():
    """หลุดกลับไปกลับมาแค่ 1 แท่งเดียว (noise ตรง threshold) ต้องไม่ถูกนับว่าเปลี่ยน regime จริง
    ถ้าตั้ง confirm_bars=3"""
    raw = pd.Series(["trend", "trend", "trend", "range", "trend", "trend", "trend", "trend"])
    result = _apply_hysteresis(raw, confirm_bars=3)
    # "range" ตัวเดียวแทรกกลาง trend ยาวๆ ไม่ควรทำให้ label เปลี่ยนเป็น range เลย (confirm ไม่ครบ 3)
    assert (result == "trend").all()


def test_hysteresis_confirms_genuine_regime_change():
    """ถ้า raw label ใหม่คงที่ครบ confirm_bars แท่งจริงๆ ต้องเปลี่ยน label สำเร็จ (ไม่ใช่ค้างตลอดไป)"""
    raw = pd.Series(["trend"] * 5 + ["range"] * 5)
    result = _apply_hysteresis(raw, confirm_bars=3)
    assert result.iloc[:5].eq("trend").all()
    # หลังแท่งที่ 3 ของ "range" ติดต่อกัน (index 5,6,7 -> confirm ที่ index 7) ต้องเปลี่ยนเป็น range
    assert result.iloc[7:].eq("range").all()
    assert result.iloc[5] == "trend"  # ยังไม่ confirm ครบ ยังคงป้ายเดิม
    assert result.iloc[6] == "trend"


def test_compute_regime_with_confirm_bars_reduces_switch_count_vs_raw():
    """เปิด hysteresis (confirm_bars>1) ต้องทำให้จำนวนครั้งที่ regime เปลี่ยนป้ายน้อยลงหรือเท่าเดิม
    เทียบกับไม่เปิด (confirm_bars=1) — วัดผลบนข้อมูลจริงที่มี noise
    """
    rng = np.random.default_rng(9)
    steps = rng.normal(0, 0.4, size=800)
    close = 1950.0 + np.cumsum(steps)
    df = _make_df(close)

    raw = compute_regime(df, confirm_bars=1)
    smoothed = compute_regime(df, confirm_bars=4)

    raw_switches = (raw != raw.shift(1)).sum()
    smoothed_switches = (smoothed != smoothed.shift(1)).sum()
    assert smoothed_switches <= raw_switches

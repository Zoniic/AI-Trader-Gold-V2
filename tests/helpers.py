"""ตัวช่วยสร้างข้อมูลสังเคราะห์สำหรับเทสต์ — ไม่ใช่ราคาจริง ใช้พิสูจน์ logic เท่านั้น"""
import numpy as np
import pandas as pd


def make_synthetic_df(n: int, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    steps = rng.normal(0, 0.5, size=n)
    close = 1950.0 + np.cumsum(steps)
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

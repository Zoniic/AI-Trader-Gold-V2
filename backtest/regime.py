"""จำแนกสภาพตลาดแต่ละแท่งเป็น trend / range / volatile / low_volatility

ใช้ ADX (มาตรฐาน Wilder) วัดความแรงเทรนด์ + ATR/ราคา วัดความผันผวน ไม่พึ่ง library ภายนอก
ทุกค่าคำนวณแบบ rolling ย้อนหลังเท่านั้น (ไม่มองอนาคต) ปลอดภัยต่อการใช้ใน backtest

4 สภาวะ (Market Condition ตาม SOP ข้อ 17):
- volatile:       ATR สูงผิดปกติ (>P80) — ข่าวแรง/ตลาดคลั่ง (ชนะทุกป้ายอื่น)
- trend:          ADX >= 25 — มีทิศทางชัด
- low_volatility: ATR ต่ำผิดปกติ (<P25) และไม่เทรนด์ — ตลาดหลับ สเปรดกินสัดส่วนสูง
- range:          ที่เหลือ — แกว่งกรอบปกติ
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TREND_ADX_THRESHOLD = 25.0
VOLATILE_PERCENTILE = 0.80
LOW_VOL_PERCENTILE = 0.25
PERCENTILE_LOOKBACK = 500


def _wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1 / period, adjust=False).mean()


def _true_range(df: pd.DataFrame) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    return pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)


def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low = df["high"], df["low"]
    prev_high, prev_low = high.shift(1), low.shift(1)

    tr = _true_range(df)
    plus_dm = (high - prev_high).clip(lower=0)
    minus_dm = (prev_low - low).clip(lower=0)
    # เอาแค่ทิศทางที่แรงกว่าตามสูตร Wilder (ถ้าเท่ากันหรือแพ้ให้เป็น 0)
    plus_dm_final = plus_dm.where(plus_dm > minus_dm, 0.0)
    minus_dm_final = minus_dm.where(minus_dm > plus_dm, 0.0)

    atr = _wilder_smooth(tr, period)
    plus_di = 100 * _wilder_smooth(plus_dm_final, period) / atr.replace(0, np.nan)
    minus_di = 100 * _wilder_smooth(minus_dm_final, period) / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return _wilder_smooth(dx.fillna(0), period)


def compute_atr_ratio(df: pd.DataFrame, period: int = 14) -> pd.Series:
    atr = _wilder_smooth(_true_range(df), period)
    return atr / df["close"]


def compute_regime(
    df: pd.DataFrame,
    adx_period: int = 14,
    atr_period: int = 14,
    trend_adx_threshold: float = TREND_ADX_THRESHOLD,
    volatile_percentile: float = VOLATILE_PERCENTILE,
    low_vol_percentile: float = LOW_VOL_PERCENTILE,
    percentile_lookback: int = PERCENTILE_LOOKBACK,
) -> pd.Series:
    """คืน Series ค่า 'trend' / 'range' / 'volatile' / 'low_volatility' index ตรงกับ df

    ลำดับความสำคัญ: volatile > trend > low_volatility > range
    (ผันผวนสูงสำคัญกว่าทิศทาง เช่นตอนข่าวแรง; ตลาดหลับก็ต้องรู้เพราะสเปรดกินกำไรสัดส่วนสูง)
    """
    adx = compute_adx(df, adx_period)
    atr_ratio = compute_atr_ratio(df, atr_period)
    rolling = atr_ratio.rolling(percentile_lookback, min_periods=50)
    vol_threshold = rolling.quantile(volatile_percentile)
    low_threshold = rolling.quantile(low_vol_percentile)

    regime = pd.Series("range", index=df.index)
    regime[(atr_ratio <= low_threshold) & (adx < trend_adx_threshold)] = "low_volatility"
    regime[adx >= trend_adx_threshold] = "trend"
    regime[atr_ratio >= vol_threshold] = "volatile"
    return regime

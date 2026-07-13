"""แก้ปัญหา multiple-testing bias: ยิ่งลอง config เยอะ (โปรเจกต์นี้มี ~40+ ชุด กลยุทธ์×timeframe)
ยิ่งมีโอกาสสูงที่ผลดีที่สุดเป็นแค่ noise ที่บังเอิญ fit กับข้อมูลชุดนั้น ไม่ใช่ edge จริง

ใช้ 2 เครื่องมือมาตรฐานวงการ quant:
1. Bonferroni correction — ปรับ significance threshold ตามจำนวนครั้งที่ลอง (n_trials)
2. Deflated Sharpe Ratio (Bailey & López de Prado, 2014) — เทียบ Sharpe ที่วัดได้กับ Sharpe สูงสุด
   ที่ "คาดว่าจะเจอโดยบังเอิญ" ถ้าทดลองสุ่ม n_trials ครั้ง (ยิ่งลองเยอะ ยิ่งมีโอกาสเจอ SR สูงจากบังเอิญ)
   ถ้า DSR ต่ำ = Sharpe ที่เห็นอาจเป็นแค่ผลจาก data-mining ไม่ใช่ edge จริง

อ้างอิง: Bailey, D. and López de Prado, M. (2014). "The Deflated Sharpe Ratio: Correcting for
Selection Bias, Backtest Overfitting, and Non-Normality." Journal of Portfolio Management.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats

EULER_MASCHERONI = 0.5772156649015329


def bonferroni_alpha(n_trials: int, alpha: float = 0.05) -> float:
    """threshold ที่ปรับแล้วสำหรับ significance test เมื่อทดลอง n_trials ครั้งอิสระกัน
    (ยิ่ง n_trials เยอะ threshold ยิ่งเข้มขึ้น กัน false positive จากการลองซ้ำหลายรอบ)
    """
    if n_trials < 1:
        raise ValueError("n_trials ต้อง >= 1")
    return alpha / n_trials


def sharpe_ratio(pnls: list[float] | np.ndarray) -> float:
    """Sharpe ratio ระดับ "ต่อไม้" (ไม่ annualize เพราะความถี่ของไม้ไม่คงที่ข้าม timeframe/กลยุทธ์)
    ใช้เปรียบเทียบสัมพัทธ์ระหว่างกลยุทธ์/config เท่านั้น ไม่ใช่ Sharpe แบบ annualized ทั่วไป
    """
    arr = np.asarray(pnls, dtype=float)
    if len(arr) < 2 or arr.std(ddof=1) == 0:
        return 0.0
    return float(arr.mean() / arr.std(ddof=1))


@dataclass
class DeflatedSharpeResult:
    observed_sharpe: float
    expected_max_sharpe_by_chance: float  # SR สูงสุดที่คาดว่าจะเจอโดยบังเอิญจาก n_trials ครั้ง
    deflated_sharpe_ratio: float  # ความน่าจะเป็นที่ observed_sharpe จริงเกินกว่าโอกาสบังเอิญ (0-1)
    n_trials: int
    is_significant: bool  # DSR > 0.95 = ผ่านเกณฑ์ทั่วไปของวงการ (95% confidence)


def deflated_sharpe_ratio(
    observed_pnls: list[float] | np.ndarray,
    n_trials: int,
    trial_sharpe_std: float | None = None,
) -> DeflatedSharpeResult:
    """คำนวณ Deflated Sharpe Ratio ของกลยุทธ์ตัวหนึ่ง เทียบกับ "โชค" ที่คาดว่าจะเจอถ้าทดลอง
    n_trials ครั้งอิสระกัน (เช่น ~40 ชุด กลยุทธ์×timeframe ที่ลองใน configs/)

    trial_sharpe_std: ส่วนเบี่ยงเบนมาตรฐานของ Sharpe ratio ข้าม trial ทั้งหมด — ถ้าไม่ระบุ ใช้ 1.0
    เป็นค่าอนุรักษ์นิยม (สมมติ Sharpe กระจายตัวเท่ากับหน่วยมาตรฐาน)
    """
    arr = np.asarray(observed_pnls, dtype=float)
    n = len(arr)
    observed_sr = sharpe_ratio(arr)

    if n < 3:
        return DeflatedSharpeResult(
            observed_sharpe=observed_sr, expected_max_sharpe_by_chance=0.0,
            deflated_sharpe_ratio=0.0, n_trials=n_trials, is_significant=False,
        )

    skew = float(stats.skew(arr))
    kurt = float(stats.kurtosis(arr, fisher=False))  # excess=False -> normal kurtosis=3

    sr_std = trial_sharpe_std if trial_sharpe_std is not None else 1.0
    if n_trials <= 1:
        expected_max_sr = 0.0  # ทดลองครั้งเดียวไม่มี selection bias ต้องกัน
    else:
        z1 = stats.norm.ppf(1 - 1.0 / n_trials)
        z2 = stats.norm.ppf(1 - 1.0 / (n_trials * math.e))
        expected_max_sr = sr_std * ((1 - EULER_MASCHERONI) * z1 + EULER_MASCHERONI * z2)

    denom = math.sqrt(max(1e-12, 1 - skew * observed_sr + (kurt - 1) / 4 * observed_sr**2))
    psr_stat = (observed_sr - expected_max_sr) * math.sqrt(n - 1) / denom
    dsr = float(stats.norm.cdf(psr_stat))

    return DeflatedSharpeResult(
        observed_sharpe=observed_sr,
        expected_max_sharpe_by_chance=expected_max_sr,
        deflated_sharpe_ratio=dsr,
        n_trials=n_trials,
        is_significant=dsr > 0.95,
    )

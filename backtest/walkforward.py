"""ตรวจความสม่ำเสมอนอกช่วงข้อมูล (out-of-sample) กัน overfitting

หมายเหตุ: กลยุทธ์ตอนนี้ (ema_cross) ไม่มีพารามิเตอร์ที่ต้อง fit จากข้อมูล จึงไม่ใช่
walk-forward แบบ "train แล้ว refit ทุก fold" ตามตำรา — ที่ทำตรงนี้คือแบ่งข้อมูลเป็น
ช่วงต่อเนื่องหลาย fold แล้วรัน backtest อิสระในแต่ละ fold เพื่อเช็คว่าผลบวก/ลบ
สม่ำเสมอข้ามช่วงเวลาจริงหรือเป็นแค่ fluke ของช่วงใดช่วงหนึ่ง ถ้าจะเพิ่มกลยุทธ์ที่มี
พารามิเตอร์ให้ optimize ทีหลัง ค่อยต่อยอดเป็น train/test แยกจริงจากโครงนี้ได้
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from backtest.costs import CostModel
from backtest.engine import TradeManagement, run_backtest
from backtest.metrics import summarize
from backtest.stats import DeflatedSharpeResult, deflated_sharpe_ratio
from core.signal import MarketData
from core.strategy import Strategy
from risk.position_sizing import RiskConfig

DEFAULT_MIN_TRADES_PER_FOLD = 15
DEFAULT_HOLDOUT_FRACTION = 0.15


@dataclass
class FoldResult:
    fold: int
    period_start: pd.Timestamp
    period_end: pd.Timestamp
    metrics: dict
    conclusive: bool  # จำนวนเทรด >= min_trades_per_fold ไหม


@dataclass
class WalkForwardReport:
    strategy_name: str
    folds: list[FoldResult] = field(default_factory=list)
    pooled_metrics: dict = field(default_factory=dict)
    consistency_pct: float = 0.0
    verdict: str = ""
    deflated_sharpe: DeflatedSharpeResult | None = None


@dataclass
class HoldoutReport:
    """ผลรันบนข้อมูล holdout ที่ไม่เคยถูกแตะระหว่าง tune พารามิเตอร์เลย — ต่างจาก fold ปกติที่
    เอาไปคำนวณ consistency_pct ตรงๆ holdout นี้คือด่านสุดท้ายก่อนเชื่อว่ามี edge จริง
    """
    strategy_name: str
    period_start: pd.Timestamp
    period_end: pd.Timestamp
    metrics: dict
    deflated_sharpe: DeflatedSharpeResult
    verdict: str


def _split_fold_ranges(n_bars: int, n_folds: int) -> list[tuple[int, int]]:
    fold_size = n_bars // n_folds
    ranges = []
    for i in range(n_folds):
        start = i * fold_size
        end = n_bars if i == n_folds - 1 else (i + 1) * fold_size
        ranges.append((start, end))
    return ranges


def split_holdout(
    df: pd.DataFrame, holdout_fraction: float = DEFAULT_HOLDOUT_FRACTION
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """แบ่งข้อมูลเป็น (tuning_df, holdout_df) — holdout_df คือช่วงท้ายสุดของข้อมูล (เวลาล่าสุด)
    ที่ "ห้ามแตะ" ระหว่างขั้นตอน tune พารามิเตอร์/เลือก config ใดๆ ทั้งสิ้น เก็บไว้ประเมินครั้งเดียว
    ตอนจบเท่านั้น (ผ่าน evaluate_holdout) ถึงจะเชื่อได้ว่า edge ไม่ได้มาจากการ overfit ย้อนหลัง
    """
    if not 0.0 < holdout_fraction < 1.0:
        raise ValueError("holdout_fraction ต้องอยู่ระหว่าง 0 ถึง 1")
    split_idx = int(len(df) * (1 - holdout_fraction))
    return df.iloc[:split_idx], df.iloc[split_idx:]


def evaluate_holdout(
    strategy_factory: Callable[[], Strategy],
    holdout_data: MarketData,
    risk_cfg: RiskConfig,
    cost: CostModel,
    n_trials: int,
    management: TradeManagement | None = None,
    allowed_regimes: list[str] | None = None,
    blocked_hours: list[int] | None = None,
) -> HoldoutReport:
    """รัน backtest ครั้งเดียวบนข้อมูล holdout (จาก split_holdout) พร้อมคำนวณ Deflated Sharpe Ratio
    เทียบกับจำนวนครั้งที่ทดลอง config ทั้งหมด (n_trials) — เช่นถ้ามี 12 กลยุทธ์ × 3 timeframe = 36
    ให้ n_trials=36 ไม่ใช่ 1 ถึงจะสะท้อนความเสี่ยง multiple-testing ที่แท้จริง

    เรียกฟังก์ชันนี้ "ครั้งเดียว" ต่อ config ที่ตัดสินใจใช้จริงเท่านั้น — ถ้าเรียกซ้ำแล้วปรับ config
    ตามผล holdout จะกลายเป็นการ tune บน holdout ทางอ้อม (ทำให้ holdout เสียความหมายทันที)
    """
    df = holdout_data.df
    strategy_name = strategy_factory().name
    result = run_backtest(
        strategy_factory(), holdout_data, risk_cfg, cost,
        management=management, allowed_regimes=allowed_regimes, blocked_hours=blocked_hours,
    )
    pnls = [t.pnl for t in result.trades]
    metrics = summarize(pnls, result.equity_curve, risk_cfg.account_balance)
    dsr = deflated_sharpe_ratio(pnls, n_trials=n_trials) if len(pnls) >= 3 else DeflatedSharpeResult(
        observed_sharpe=0.0, expected_max_sharpe_by_chance=0.0, deflated_sharpe_ratio=0.0,
        n_trials=n_trials, is_significant=False,
    )

    if len(pnls) < DEFAULT_MIN_TRADES_PER_FOLD:
        verdict = (
            f"ข้อมูลไม่พอสรุปบน holdout — มีแค่ {len(pnls)} เทรด (ต้องการอย่างน้อย "
            f"{DEFAULT_MIN_TRADES_PER_FOLD}) — เพิ่มช่วงข้อมูลย้อนหลัง หรือลด holdout_fraction"
        )
    elif dsr.is_significant:
        verdict = (
            f"ผ่าน holdout — DSR={dsr.deflated_sharpe_ratio:.3f} (>0.95) แม้ปรับด้วย "
            f"n_trials={n_trials} แล้ว Sharpe ที่เห็นยังมีนัยสำคัญ ไม่น่าจะเป็นแค่โชค"
        )
    else:
        verdict = (
            f"ไม่ผ่าน holdout — DSR={dsr.deflated_sharpe_ratio:.3f} (<=0.95) เมื่อปรับด้วย "
            f"n_trials={n_trials} แล้ว Sharpe ที่เห็นอาจเป็นแค่ผลจาก data-mining bias "
            "ไม่ใช่ edge จริง — ระวังก่อนเอาไป live"
        )

    return HoldoutReport(
        strategy_name=strategy_name,
        period_start=df.index[0], period_end=df.index[-1],
        metrics=metrics, deflated_sharpe=dsr, verdict=verdict,
    )


def run_walkforward(
    strategy_factory: Callable[[], Strategy],
    data: MarketData,
    risk_cfg: RiskConfig,
    cost: CostModel,
    n_folds: int = 5,
    min_trades_per_fold: int = DEFAULT_MIN_TRADES_PER_FOLD,
    management: TradeManagement | None = None,
    allowed_regimes: list[str] | None = None,
    blocked_hours: list[int] | None = None,
    n_trials: int = 1,
) -> WalkForwardReport:
    """n_trials: จำนวนชุด config อิสระที่ทดลองทั้งหมด (เช่น 12 กลยุทธ์ × 3 timeframe = 36) —
    ใส่ให้ตรงความเป็นจริงเพื่อให้ deflated_sharpe ในผลลัพธ์สะท้อน multiple-testing bias จริง
    ค่าเริ่มต้น n_trials=1 คือไม่ปรับอะไรเลย (เชื่อ Sharpe ตรงๆ) ใช้เมื่อทดสอบกลยุทธ์เดี่ยวๆ เท่านั้น
    """
    df = data.df
    strategy_name = strategy_factory().name
    folds: list[FoldResult] = []
    pooled_pnls: list[float] = []

    for fold_idx, (start, end) in enumerate(_split_fold_ranges(len(df), n_folds), start=1):
        fold_df = df.iloc[start:end]
        if len(fold_df) < 100:  # กันแฟรกเมนต์เล็กเกินไปจนไม่มีความหมาย
            continue

        fold_data = MarketData(df=fold_df, symbol=data.symbol)
        strategy = strategy_factory()
        result = run_backtest(
            strategy, fold_data, risk_cfg, cost,
            management=management, allowed_regimes=allowed_regimes,
            blocked_hours=blocked_hours,
        )
        pnls = [t.pnl for t in result.trades]
        metrics = summarize(pnls, result.equity_curve, risk_cfg.account_balance)
        conclusive = metrics["total_trades"] >= min_trades_per_fold

        folds.append(
            FoldResult(
                fold=fold_idx,
                period_start=fold_df.index[0],
                period_end=fold_df.index[-1],
                metrics=metrics,
                conclusive=conclusive,
            )
        )
        pooled_pnls.extend(pnls)

    pooled_metrics = summarize(pooled_pnls, pd.Series(dtype=float), risk_cfg.account_balance)

    conclusive_folds = [f for f in folds if f.conclusive]
    if len(conclusive_folds) <= len(folds) / 2:
        consistency_pct = 0.0
        verdict = (
            f"ข้อมูลไม่พอสรุป — fold ที่มีเทรด >= {min_trades_per_fold} เทรด มีแค่ "
            f"{len(conclusive_folds)}/{len(folds)} fold (ต้องการข้อมูลย้อนหลังมากขึ้น "
            "หรือลด min_trades_per_fold ถ้ายอมรับ sample เล็กลงได้)"
        )
    else:
        positive_folds = sum(1 for f in conclusive_folds if f.metrics["expectancy"] > 0)
        consistency_pct = positive_folds / len(conclusive_folds) * 100.0
        if consistency_pct >= 60.0:
            verdict = (
                f"ผ่าน — expectancy เป็นบวกใน {positive_folds}/{len(conclusive_folds)} "
                "fold ที่สรุปได้ (ผลค่อนข้างสม่ำเสมอข้ามช่วงเวลา)"
            )
        else:
            verdict = (
                f"ไม่ผ่าน — expectancy เป็นบวกแค่ {positive_folds}/{len(conclusive_folds)} "
                "fold ที่สรุปได้ (ผลไม่สม่ำเสมอ น่าสงสัยว่า overfit หรือ edge ไม่จริง)"
            )

    dsr = (
        deflated_sharpe_ratio(pooled_pnls, n_trials=n_trials)
        if len(pooled_pnls) >= 3 else None
    )

    return WalkForwardReport(
        strategy_name=strategy_name,
        folds=folds,
        pooled_metrics=pooled_metrics,
        consistency_pct=round(consistency_pct, 1),
        verdict=verdict,
        deflated_sharpe=dsr,
    )

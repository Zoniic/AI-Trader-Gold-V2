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
from core.signal import MarketData
from core.strategy import Strategy
from risk.position_sizing import RiskConfig

DEFAULT_MIN_TRADES_PER_FOLD = 15


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


def _split_fold_ranges(n_bars: int, n_folds: int) -> list[tuple[int, int]]:
    fold_size = n_bars // n_folds
    ranges = []
    for i in range(n_folds):
        start = i * fold_size
        end = n_bars if i == n_folds - 1 else (i + 1) * fold_size
        ranges.append((start, end))
    return ranges


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
) -> WalkForwardReport:
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

    return WalkForwardReport(
        strategy_name=strategy_name,
        folds=folds,
        pooled_metrics=pooled_metrics,
        consistency_pct=round(consistency_pct, 1),
        verdict=verdict,
    )

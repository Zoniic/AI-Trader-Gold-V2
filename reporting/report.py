"""พิมพ์สรุปผล + เซฟ trade log และกราฟ equity curve เป็นไฟล์ในโฟลเดอร์ reports/<strategy>_<timestamp>/"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from backtest.engine import BacktestResult
from backtest.metrics import summarize_by_regime
from backtest.walkforward import WalkForwardReport


def print_summary(result: BacktestResult, metrics: dict) -> None:
    print(f"\n=== ผลสรุป backtest: {result.strategy_name} ===")
    for key, value in metrics.items():
        print(f"  {key}: {value}")
    print(f"  จำนวนเทรดทั้งหมด: {len(result.trades)}")
    if result.halted_at is not None:
        print(
            f"\n  ⚠ หยุดเทรดก่อนหมดข้อมูล — kill-switch ทำงานที่ {result.halted_at} "
            f"({result.halt_reason}) ตัวเลขข้างบนนี้ไม่ครอบคลุมข้อมูลหลังจุดนี้ "
            "ดูผล run_walkforward.py ประกอบเพื่อดูว่าช่วงหลังจากนี้เป็นยังไง"
        )

    regime_breakdown = summarize_by_regime(result.trades)
    if regime_breakdown:
        print("\n  --- แยกตามสภาวะตลาด ---")
        for regime, stats in regime_breakdown.items():
            print(
                f"  {regime:10s}: trades={stats['total_trades']:4d}  "
                f"win_rate={stats['win_rate_pct']:5.1f}%  pf={stats['profit_factor']:6.3f}  "
                f"expectancy={stats['expectancy']:7.2f}  total_pnl={stats['total_pnl']:9.2f}"
            )


def _trades_to_df(result: BacktestResult) -> pd.DataFrame:
    rows = [
        {
            "direction": t.direction.value,
            "entry_time": t.entry_time,
            "entry": t.entry,
            "sl": t.sl,
            "tp": t.tp,
            "lot": t.lot,
            "exit_time": t.exit_time,
            "exit_price": t.exit_price,
            "pnl": t.pnl,
            "pnl_r": t.pnl_r,
            "mae_r": t.mae_r,
            "mfe_r": t.mfe_r,
            "post_exit_r": t.post_exit_r,
            "outcome": t.outcome,
            "regime": t.regime,
            "review": t.review,
        }
        for t in result.trades
    ]
    return pd.DataFrame(rows)


def save_trade_log(result: BacktestResult, out_dir: Path) -> Path:
    path = out_dir / "trades.csv"
    _trades_to_df(result).to_csv(path, index=False)
    return path


def save_equity_curve_plot(result: BacktestResult, out_dir: Path) -> Path:
    path = out_dir / "equity_curve.png"
    fig, ax = plt.subplots(figsize=(10, 5))
    result.equity_curve.plot(ax=ax)
    ax.set_title(f"Equity Curve — {result.strategy_name}")
    ax.set_xlabel("Time")
    ax.set_ylabel("Balance")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def print_review_summary(review_summary: dict) -> None:
    print("\n  --- บทวิเคราะห์ไม้อัตโนมัติ (MAE/MFE) ---")
    print(
        f"  ชนะเฉลี่ย {review_summary.get('avg_win_r', 0):+.2f}R / แพ้เฉลี่ย "
        f"{review_summary.get('avg_loss_r', 0):+.2f}R · "
        f"แพ้ทั้งที่เคยกำไร≥1R: {review_summary.get('losses_were_winning_1r', 0)} ไม้ · "
        f"แพ้แบบผิดทางทันที: {review_summary.get('losses_wrong_entry', 0)} ไม้"
    )
    for rec in review_summary.get("recommendations", []):
        print(f"  💡 {rec}")


def save_report(
    result: BacktestResult, metrics: dict, reports_dir: str, review_summary: dict | None = None
) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(reports_dir) / f"{result.strategy_name}_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print_summary(result, metrics)
    if review_summary:
        print_review_summary(review_summary)
    trades_path = save_trade_log(result, out_dir)
    plot_path = save_equity_curve_plot(result, out_dir)

    regime_breakdown = summarize_by_regime(result.trades)

    summary_path = out_dir / "summary.txt"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"strategy: {result.strategy_name}\n")
        for key, value in metrics.items():
            f.write(f"{key}: {value}\n")
        if result.halted_at is not None:
            f.write(f"\nhalted_at: {result.halted_at}\n")
            f.write(f"halt_reason: {result.halt_reason}\n")
        if regime_breakdown:
            f.write("\nregime_breakdown:\n")
            for regime, stats in regime_breakdown.items():
                f.write(f"  {regime}: {stats}\n")
        if review_summary:
            f.write("\nreview_summary:\n")
            for key, value in review_summary.items():
                if key != "recommendations":
                    f.write(f"  {key}: {value}\n")
            f.write("recommendations:\n")
            for rec in review_summary.get("recommendations", []):
                f.write(f"  - {rec}\n")

    regime_path = out_dir / "regime_breakdown.csv"
    if regime_breakdown:
        pd.DataFrame(regime_breakdown).T.to_csv(regime_path, index_label="regime")

    print(f"\n[report] บันทึกผลไว้ที่: {out_dir}")
    print(f"  - {trades_path.name}")
    print(f"  - {plot_path.name}")
    print(f"  - {summary_path.name}")
    if regime_breakdown:
        print(f"  - {regime_path.name}")
    return out_dir


def print_walkforward_summary(report: WalkForwardReport) -> None:
    print(f"\n=== Walk-forward: {report.strategy_name} ===")
    for f in report.folds:
        flag = "สรุปได้" if f.conclusive else "เทรดน้อยเกินไป"
        print(
            f"  fold {f.fold} [{f.period_start.date()} - {f.period_end.date()}] "
            f"({flag}): trades={f.metrics['total_trades']} "
            f"expectancy={f.metrics['expectancy']} pf={f.metrics['profit_factor']} "
            f"max_dd={f.metrics['max_drawdown_pct']}%"
        )
    print(f"\n  ความสม่ำเสมอ (fold ที่สรุปได้ + expectancy บวก): {report.consistency_pct}%")
    print(f"  รวมทุก fold (pooled): {report.pooled_metrics}")
    print(f"\n  บทสรุป: {report.verdict}")


def save_walkforward_report(report: WalkForwardReport, reports_dir: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(reports_dir) / f"walkforward_{report.strategy_name}_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print_walkforward_summary(report)

    fold_rows = [
        {
            "fold": f.fold,
            "period_start": f.period_start,
            "period_end": f.period_end,
            "conclusive": f.conclusive,
            **f.metrics,
        }
        for f in report.folds
    ]
    fold_path = out_dir / "folds.csv"
    pd.DataFrame(fold_rows).to_csv(fold_path, index=False)

    summary_path = out_dir / "summary.txt"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"strategy: {report.strategy_name}\n")
        f.write(f"consistency_pct: {report.consistency_pct}\n")
        f.write(f"verdict: {report.verdict}\n\n")
        f.write("pooled_metrics:\n")
        for key, value in report.pooled_metrics.items():
            f.write(f"  {key}: {value}\n")

    print(f"\n[report] บันทึกผล walk-forward ไว้ที่: {out_dir}")
    return out_dir

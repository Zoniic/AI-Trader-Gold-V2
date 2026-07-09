"""แผนที่ "สภาวะกราฟแบบไหน ควรใช้ทีมไหนเทรด" — คำนวณจากผลรันล่าสุดของแต่ละ (ทีม, TF)

ตอบคำถาม: ใน trend/range/volatile ใครทำกำไรมากสุด/expectancy ดีสุด
มี guard ขั้นต่ำจำนวนไม้ต่อช่อง (default 15) — ช่องที่ไม้น้อยกว่านั้นไม่มีสิทธิ์เป็นแชมป์
เพราะ sample เล็กสรุปไม่ได้ (บทเรียนเดียวกับ walk-forward)
"""
from __future__ import annotations

import pandas as pd

from persistence.db import get_trades, list_runs

REGIMES = ["trend", "range", "volatile", "low_volatility"]


def _latest_runs_per_team_tf(runs: pd.DataFrame) -> pd.DataFrame:
    """run ล่าสุดที่จบแล้ว ของแต่ละคู่ (strategy, timeframe) — runs เรียงใหม่สุดก่อนอยู่แล้ว"""
    finished = runs[runs["finished_at"].notna()].copy()
    finished["timeframe"] = finished["timeframe"].fillna("H1")
    return finished.drop_duplicates(subset=["strategy", "timeframe"], keep="first")


def compute_regime_league(db_path: str, min_trades: int = 15) -> dict:
    """คืน {"matrix": [...], "champions": [...]} สำหรับ dashboard/API"""
    runs = list_runs(db_path)
    if runs.empty:
        return {"matrix": [], "champions": []}

    latest = _latest_runs_per_team_tf(runs)

    matrix_rows: list[dict] = []
    for run in latest.itertuples():
        trades = get_trades(db_path, run.run_id)
        if trades.empty:
            continue
        grouped = trades.groupby(trades["regime"].fillna("unknown"))["pnl"]
        for regime, pnls in grouped:
            if regime not in REGIMES:
                continue
            matrix_rows.append(
                {
                    "timeframe": run.timeframe,
                    "regime": regime,
                    "strategy": run.strategy,
                    "run_id": run.run_id,
                    "total_trades": int(len(pnls)),
                    "win_rate_pct": round(float((pnls > 0).sum() / len(pnls) * 100), 1),
                    "expectancy": round(float(pnls.mean()), 2),
                    "total_pnl": round(float(pnls.sum()), 2),
                    "qualified": bool(len(pnls) >= min_trades),
                }
            )

    champions: list[dict] = []
    matrix_df = pd.DataFrame(matrix_rows)
    if not matrix_df.empty:
        for (timeframe, regime), cell in matrix_df.groupby(["timeframe", "regime"]):
            qualified = cell[cell["qualified"]]
            if qualified.empty:
                champions.append(
                    {"timeframe": timeframe, "regime": regime, "champion": None,
                     "note": f"ไม่มีทีมไหนมีไม้ถึง {min_trades} ไม้ในช่องนี้"}
                )
                continue
            best = qualified.sort_values("total_pnl", ascending=False).iloc[0]
            runner_up = (
                qualified.sort_values("total_pnl", ascending=False).iloc[1]
                if len(qualified) > 1 else None
            )
            champions.append(
                {
                    "timeframe": timeframe,
                    "regime": regime,
                    "champion": best["strategy"],
                    "total_pnl": float(best["total_pnl"]),
                    "expectancy": float(best["expectancy"]),
                    "win_rate_pct": float(best["win_rate_pct"]),
                    "total_trades": int(best["total_trades"]),
                    "profitable": bool(best["total_pnl"] > 0),
                    "runner_up": runner_up["strategy"] if runner_up is not None else None,
                    "note": "",
                }
            )

    return {"matrix": matrix_rows, "champions": champions}

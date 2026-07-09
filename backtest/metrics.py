"""ฟังก์ชันคำนวณสถิติผล backtest — pure function ไม่ผูกกับ engine"""
from __future__ import annotations

import pandas as pd


def win_rate(trade_pnls: list[float]) -> float:
    if not trade_pnls:
        return 0.0
    wins = sum(1 for p in trade_pnls if p > 0)
    return wins / len(trade_pnls) * 100.0


def profit_factor(trade_pnls: list[float]) -> float:
    gross_profit = sum(p for p in trade_pnls if p > 0)
    gross_loss = abs(sum(p for p in trade_pnls if p < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def max_drawdown(equity_curve: pd.Series) -> float:
    if equity_curve.empty:
        return 0.0
    running_peak = equity_curve.cummax()
    drawdown_pct = (equity_curve - running_peak) / running_peak * 100.0
    return float(drawdown_pct.min())


def expectancy(trade_pnls: list[float]) -> float:
    if not trade_pnls:
        return 0.0
    return sum(trade_pnls) / len(trade_pnls)


def summarize(trade_pnls: list[float], equity_curve: pd.Series, initial_balance: float) -> dict:
    return {
        "total_trades": len(trade_pnls),
        "win_rate_pct": round(win_rate(trade_pnls), 2),
        "profit_factor": round(profit_factor(trade_pnls), 3),
        "max_drawdown_pct": round(max_drawdown(equity_curve), 2),
        "expectancy": round(expectancy(trade_pnls), 2),
        "total_pnl": round(sum(trade_pnls), 2),
        "final_balance": round(initial_balance + sum(trade_pnls), 2),
    }


def summarize_by_regime(trades: list) -> dict[str, dict]:
    """แยกผลตาม regime ของแต่ละเทรด (trend/range/volatile) — เทียบว่าทีมไหนเก่งตอนไหน

    ไม่รวม max_drawdown เพราะ drawdown มีความหมายเฉพาะเมื่อดูลำดับเทรดต่อเนื่องทั้งหมด
    แยกตาม regime แล้วจะไม่ใช่ drawdown จริงของพอร์ต
    """
    by_regime: dict[str, list[float]] = {}
    for t in trades:
        by_regime.setdefault(t.regime or "unknown", []).append(t.pnl)

    result: dict[str, dict] = {}
    for regime, pnls in by_regime.items():
        result[regime] = {
            "total_trades": len(pnls),
            "win_rate_pct": round(win_rate(pnls), 2),
            "profit_factor": round(profit_factor(pnls), 3),
            "expectancy": round(expectancy(pnls), 2),
            "total_pnl": round(sum(pnls), 2),
        }
    return result

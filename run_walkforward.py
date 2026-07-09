"""Entrypoint: ตรวจความสม่ำเสมอนอกช่วงข้อมูล (out-of-sample) ก่อนเชื่อผลจาก run_backtest.py

ใช้งาน: python run_walkforward.py [--strategy ema_cross|mean_reversion]
"""
from __future__ import annotations

import argparse
import sys

from backtest.costs import CostModel
from backtest.engine import TradeManagement
from backtest.walkforward import run_walkforward
from config import load_settings
from core.strategy import STRATEGY_REGISTRY
from core.team_config import load_team_config
from data.loader import load_price_data
from reporting.report import save_walkforward_report
from risk.position_sizing import RiskConfig
import strategies  # noqa: F401  (import ทำให้ @register_strategy ทำงาน เติม registry)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--strategy",
        default="ema_cross",
        help=f"ชื่อทีมที่จะรัน (มี: {', '.join(STRATEGY_REGISTRY.keys())})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.strategy not in STRATEGY_REGISTRY:
        print(
            f"ไม่รู้จักทีม '{args.strategy}' — ทีมที่มี: {', '.join(STRATEGY_REGISTRY.keys())}"
        )
        sys.exit(1)

    settings = load_settings()
    data = load_price_data(settings)

    strategy_cls = STRATEGY_REGISTRY[args.strategy]
    team_cfg = load_team_config(args.strategy, strategy_cls, timeframe=settings.timeframe)
    management = TradeManagement(**team_cfg["trade_management"])
    min_approvals = team_cfg.get("min_approvals", 4)

    def make_strategy():
        strategy = strategy_cls(**team_cfg["strategy_params"])
        if hasattr(strategy, "_committee"):
            strategy._committee.min_approvals = min_approvals
        return strategy

    team_risk = team_cfg.get("risk") or {}
    risk_cfg = RiskConfig(
        account_balance=settings.initial_balance,
        risk_per_trade_pct=team_risk.get("risk_per_trade_pct", settings.risk_per_trade_pct),
        max_drawdown_pct=team_risk.get("max_drawdown_pct", settings.max_drawdown_pct),
        max_daily_loss_pct=team_risk.get("max_daily_loss_pct"),
        max_weekly_loss_pct=team_risk.get("max_weekly_loss_pct"),
        sizing_mode=team_risk.get("sizing_mode", "fixed"),
        dd_targeting=team_risk.get("dd_targeting", False),
        dd_budget_headroom=team_risk.get("dd_budget_headroom", 0.3),
        dd_budget_boost_cap=team_risk.get("dd_budget_boost_cap", 1.3),
        dd_budget_floor=team_risk.get("dd_budget_floor", 0.4),
    )
    cost = CostModel(spread_points=settings.spread_points, slippage_points=settings.slippage_points)

    print(f"[config] ใช้ {team_cfg.get('_config_file', '(default)')} + management + regime gate เดียวกับ backtest")
    report = run_walkforward(
        strategy_factory=make_strategy,
        data=data,
        risk_cfg=risk_cfg,
        cost=cost,
        n_folds=5,
        min_trades_per_fold=15,
        management=management,
        allowed_regimes=team_cfg.get("allowed_regimes"),
        blocked_hours=team_cfg.get("blocked_hours"),
    )

    save_walkforward_report(report, settings.reports_dir)


if __name__ == "__main__":
    main()

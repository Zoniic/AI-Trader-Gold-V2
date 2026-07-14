"""Entrypoint: โหลดข้อมูล -> รันกลยุทธ์ผ่าน backtest engine -> เซฟรายงาน + บทวิเคราะห์

ใช้งาน: python run_backtest.py [--strategy <team>]
setting ของทีมอ่านจาก configs/<team>.json (สร้างอัตโนมัติครั้งแรก) และ snapshot ลง DB ทุกรัน
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from backtest.costs import CostModel
from backtest.engine import TradeManagement, run_backtest
from backtest.metrics import summarize
from backtest.review import aggregate_review
from config import load_settings
from core.strategy import STRATEGY_REGISTRY
from core.team_config import load_team_config
from data.loader import load_price_data
from execution.alerts import send_discord_alert
from persistence.db import RunLogger
from reporting.report import save_report
from risk.position_sizing import RiskConfig
import strategies  # noqa: F401  (import ทำให้ @register_strategy ทำงาน เติม registry)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--strategy",
        default="ema_cross",
        help=f"ชื่อทีมที่จะรัน (มี: {', '.join(STRATEGY_REGISTRY.keys())})",
    )
    parser.add_argument(
        "--pre-trade-gate", action="store_true",
        help="เปิดโต๊ะความเสี่ยงกลาง ประเมินบริบท 17 ข้อก่อนทุกไม้ (ข้ามไม้คุณภาพต่ำ)",
    )
    parser.add_argument(
        "--pre-trade-min-quality", type=float, default=0.0,
        help="ข้ามไม้ที่ quality_score ต่ำกว่าค่านี้ (0-100)",
    )
    parser.add_argument(
        "--disable-dd-halt", action="store_true",
        help="ไม่หยุดเทรดถาวรแม้ DD เกินเพดาน (ใช้ทดสอบว่า kill-switch ช่วยจริงไหม)",
    )
    parser.add_argument(
        "--confirm-bars", type=int, default=0,
        help="ไม้กระดาษยืนยันทิศก่อนเข้าจริง: ดูไปกี่แท่ง (0 = ปิด)",
    )
    parser.add_argument(
        "--confirm-threshold-r", type=float, default=0.3,
        help="ราคาต้องไปทางเรากี่ R ถึงยืนยันเข้าไม้จริง",
    )
    parser.add_argument(
        "--discord-alert", action="store_true",
        help="ส่ง Discord แจ้งเตือนเปิด/ปิดไม้เหมือน live (ใช้ DISCORD_WEBHOOK_URL_DRY_RUN) "
             "จำกัดแค่ N ไม้แรก (ดู --discord-alert-limit) กัน spam/rate-limit",
    )
    parser.add_argument(
        "--discord-alert-limit", type=int, default=10,
        help="จำนวนไม้สูงสุดที่จะแจ้งเตือน Discord ตอน backtest (ค่าเริ่มต้น 10)",
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
    strategy = strategy_cls(**team_cfg["strategy_params"])
    management = TradeManagement(**team_cfg["trade_management"])
    allowed_regimes = team_cfg.get("allowed_regimes")
    min_approvals = team_cfg.get("min_approvals", 4)
    if hasattr(strategy, "_committee"):
        strategy._committee.min_approvals = min_approvals

    # risk ต่อทีม (SOP: ทีมพิสูจน์แล้วเสี่ยงได้มากกว่า) — override ค่า global จาก .env ได้ใน config
    team_risk = team_cfg.get("risk") or {}
    risk_cfg = RiskConfig(
        account_balance=settings.initial_balance,
        contract_size=settings.contract_size,
        risk_per_trade_pct=team_risk.get("risk_per_trade_pct", settings.risk_per_trade_pct),
        max_drawdown_pct=team_risk.get("max_drawdown_pct", settings.max_drawdown_pct),
        max_daily_loss_pct=team_risk.get("max_daily_loss_pct"),
        max_weekly_loss_pct=team_risk.get("max_weekly_loss_pct"),
        sizing_mode=team_risk.get("sizing_mode", "fixed"),
        dd_targeting=team_risk.get("dd_targeting", False),
        dd_budget_headroom=team_risk.get("dd_budget_headroom", 0.3),
        dd_budget_boost_cap=team_risk.get("dd_budget_boost_cap", 1.3),
        dd_budget_floor=team_risk.get("dd_budget_floor", 0.4),
        dd_halt_mode=team_risk.get("dd_halt_mode", "permanent"),
        dd_probation_scale=team_risk.get("dd_probation_scale", 0.35),
        dd_resume_pct=team_risk.get("dd_resume_pct", 10.0),
    )
    cost = CostModel(spread_points=settings.spread_points, slippage_points=settings.slippage_points,
                     point_value=settings.point_value)

    # snapshot ทุก setting ที่มีผลต่อผลลัพธ์ — บันทึกลง DB คู่กับ run เสมอ
    config_snapshot = {
        "config_file": team_cfg.get("_config_file", "(default)"),
        "strategy_params": team_cfg["strategy_params"],
        "trade_management": team_cfg["trade_management"],
        "allowed_regimes": allowed_regimes,
        "min_approvals": min_approvals,
        "risk": {
            "initial_balance": settings.initial_balance,
            "risk_per_trade_pct": risk_cfg.risk_per_trade_pct,
            "max_drawdown_pct": risk_cfg.max_drawdown_pct,
            "max_daily_loss_pct": risk_cfg.max_daily_loss_pct,
            "max_weekly_loss_pct": risk_cfg.max_weekly_loss_pct,
            "sizing_mode": risk_cfg.sizing_mode,
            "dd_targeting": risk_cfg.dd_targeting,
            "dd_budget_headroom": risk_cfg.dd_budget_headroom,
            "dd_budget_boost_cap": risk_cfg.dd_budget_boost_cap,
            "dd_budget_floor": risk_cfg.dd_budget_floor,
        },
        "cost": {
            "spread_points": settings.spread_points,
            "slippage_points": settings.slippage_points,
        },
        "symbol": settings.symbol,
        "timeframe": settings.timeframe,
    }

    run_id = f"{strategy.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    logger = RunLogger(settings.log_db_path, run_id=run_id)
    logger.start_run(
        strategy.name,
        settings.initial_balance,
        timeframe=settings.timeframe,
        config=json.dumps(config_snapshot, ensure_ascii=False),
        symbol=settings.symbol,
    )
    print(f"[log] บันทึกทุก signal/decision/trade ลง: {settings.log_db_path} (run_id={run_id})")

    if args.discord_alert:
        send_discord_alert(
            f"🟢 **เริ่ม backtest** — `{strategy.name}` timeframe={settings.timeframe} "
            f"balance เริ่มต้น=${settings.initial_balance:,.2f} run_id={run_id}",
            settings.discord_webhook_url_dry_run, level="info", dedupe_key=None,
        )

    result = run_backtest(
        strategy, data, risk_cfg, cost,
        logger=logger, management=management, allowed_regimes=allowed_regimes,
        blocked_hours=team_cfg.get("blocked_hours"),
        pre_trade_gate=args.pre_trade_gate,
        pre_trade_min_quality=args.pre_trade_min_quality,
        disable_dd_halt=args.disable_dd_halt,
        entry_confirm_bars=args.confirm_bars,
        entry_confirm_threshold_r=args.confirm_threshold_r,
        discord_webhook_url=settings.discord_webhook_url_dry_run if args.discord_alert else None,
        discord_alert_limit=args.discord_alert_limit,
    )

    trade_pnls = [t.pnl for t in result.trades]
    metrics = summarize(trade_pnls, result.equity_curve, settings.initial_balance)
    logger.finish_run(metrics, halted_at=result.halted_at, halt_reason=result.halt_reason)
    logger.close()

    review_summary = aggregate_review(result.trades)
    save_report(result, metrics, settings.reports_dir, review_summary=review_summary)


if __name__ == "__main__":
    main()

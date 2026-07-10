"""FastAPI ภายใน — อ่านอย่างเดียวจาก trading_log.db ไม่รับ request จาก LAN โดยตรง

Next.js (web/frontend) เป็นตัวเดียวที่คุยกับ browser และ proxy มาเรียก API นี้แบบ
server-to-server (ไม่มีปัญหา CORS เพราะไม่ใช่ browser เรียกตรง) — เหตุนี้จึง bind
127.0.0.1 เท่านั้น ห้ามเปิดเป็น 0.0.0.0 เด็ดขาด (จะข้ามชั้น auth ของ Next.js ไปเลย)

รัน (จาก root ของโปรเจกต์ AI Trader V2):
    uvicorn web.backend.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException

from analysis.council import run_council
from backtest.regime_league import compute_regime_league
from backtest.review import aggregate_review_from_rows
from config import load_settings
from core.strategy import STRATEGY_REGISTRY
from persistence.db import get_decisions, get_trades, list_runs
from portfolio.simulate import simulate_portfolio
import strategies  # noqa: F401  (import ทำให้ @register_strategy ทำงาน เติม registry)

# รอบ5: คัดใหม่หลัง snowball grid — เหมือน run_portfolio.py::CORE_SELECTIONS
# (เลี่ยงทีม M15 เพราะข้อมูลเริ่มแค่ 2025-07 จะหดหน้าต่างเวลาร่วมของพอร์ตทั้งก้อน)
PORTFOLIO_SELECTIONS = [
    ("trend_pullback", "M30", 1.0),
    ("london_breakout", "M30", 1.0),
    ("trend_pullback", "H1", 0.5),
    ("rsi_divergence", "M30", 0.5),
    ("donchian_breakout", "H1", 0.5),
    ("ema_cross", "M30", 0.5),
    ("vwap_reversion", "H1", 0.25),
    ("volatility_breakout", "H1", 0.25),
    # fib_confluence M30 ผ่าน walk-forward แต่เจือจางพอร์ตนี้ (ทดสอบแล้ว) — ไม่รวม
]

app = FastAPI(title="AI Trader V2 API (internal)")


def _sanitize(df: pd.DataFrame) -> list[dict]:
    """แทน NaN/inf ด้วย None ก่อนส่งเป็น JSON เพราะ NaN/Infinity ไม่ใช่ JSON ที่ถูกต้อง"""
    clean = df.replace([np.inf, -np.inf], np.nan)
    return clean.where(clean.notna(), None).to_dict(orient="records")


def _regime_breakdown(trades_df: pd.DataFrame) -> list[dict]:
    if trades_df.empty:
        return []
    grouped = trades_df.groupby(trades_df["regime"].fillna("unknown"))["pnl"]
    rows = []
    for regime, pnls in grouped:
        gross_profit = pnls[pnls > 0].sum()
        gross_loss = abs(pnls[pnls < 0].sum())
        profit_factor = (
            (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
        )
        rows.append(
            {
                "regime": regime,
                "total_trades": int(len(pnls)),
                "win_rate_pct": round(float((pnls > 0).sum() / len(pnls) * 100), 1),
                "profit_factor": None if profit_factor == float("inf") else round(float(profit_factor), 3),
                "expectancy": round(float(pnls.mean()), 2),
                "total_pnl": round(float(pnls.sum()), 2),
            }
        )
    return rows


@app.get("/strategies")
def api_list_strategies() -> list[dict]:
    """รายชื่อทีมทั้งหมด พร้อมคำอธิบายท่าเทรด พารามิเตอร์ และรายชื่อนักเทรด 5 คนในทีม"""
    result = []
    for strategy_name, strategy_cls in STRATEGY_REGISTRY.items():
        instance = strategy_cls()
        result.append(
            {
                "name": strategy_name,
                "description": strategy_cls.description,
                "params": instance.params(),
                "committee": instance.committee_info(),
            }
        )
    return result


@app.get("/regime-champions")
def api_regime_champions(min_trades: int = 15) -> dict:
    """แผนที่ 'สภาวะกราฟแบบไหน ใช้ทีมไหนเทรด' จากผลรันล่าสุดต่อ (ทีม, timeframe)"""
    settings = load_settings()
    return compute_regime_league(settings.log_db_path, min_trades=min_trades)


@app.get("/council")
def api_council() -> dict:
    """สภานักวิเคราะห์ AI 4 มุม (Risk/Edge/Discipline/Psychology) สรุปจาก DB ล่าสุด"""
    settings = load_settings()
    return run_council(settings.log_db_path)


@app.get("/portfolio")
def api_portfolio(multipliers: str = "1,2,4,8") -> dict:
    """จำลองพอร์ตรวมทุกทีม + ทดสอบตัวคูณความเสี่ยงหลายระดับ — ตอบคำถามเป้าผลตอบแทน/เดือน vs DD/โอกาสเจ๊ง"""
    settings = load_settings()
    rows = []
    monthly_at_1x = []
    for m_str in multipliers.split(","):
        m = float(m_str)
        try:
            result = simulate_portfolio(
                settings.log_db_path, PORTFOLIO_SELECTIONS,
                initial_balance=settings.initial_balance, risk_multiplier=m,
                dd_targeting=True,  # กันบัญชีเจ๊งตอน over-leverage (หด lot ตอน DD ลึก)
            )
        except ValueError as exc:
            return {"error": str(exc), "selections": PORTFOLIO_SELECTIONS}
        rets = [mo["return_pct"] for mo in result.monthly_returns]
        rows.append(
            {
                "multiplier": m,
                "final_balance": result.final_balance,
                "max_drawdown_pct": result.max_drawdown_pct,
                "avg_monthly_return_pct": round(sum(rets) / len(rets), 1) if rets else 0.0,
                "worst_month_pct": round(min(rets), 1) if rets else 0.0,
                "best_month_pct": round(max(rets), 1) if rets else 0.0,
                "trades_taken": result.taken,
                "ruined": result.ruined,
            }
        )
        if m == 1.0:
            monthly_at_1x = result.monthly_returns

    return {
        "selections": [{"strategy": s, "timeframe": tf, "risk_pct": r} for s, tf, r in PORTFOLIO_SELECTIONS],
        "initial_balance": settings.initial_balance,
        "multiplier_comparison": rows,
        "monthly_returns_1x": monthly_at_1x,
    }


@app.get("/runs")
def api_list_runs() -> list[dict]:
    settings = load_settings()
    return _sanitize(list_runs(settings.log_db_path))


@app.get("/live/status")
def api_live_status() -> dict:
    """สถานะ live/paper runner แบบ realtime — เช็ค heartbeat ล่าสุดว่ายังอยู่ (< 3 นาที) หรือตาย

    frontend poll endpoint นี้ทุก 5-10 วิ ไม่ต้องมี live_runner รันอยู่ก็เรียกได้ (คืน list ว่าง)
    """
    from datetime import datetime, timedelta, timezone

    settings = load_settings()
    runs_df = list_runs(settings.log_db_path)
    live_runs = runs_df[runs_df["run_id"].str.startswith("live_", na=False)]
    if live_runs.empty:
        return {"active": False, "teams": []}

    # SQLite datetime('now') คืนค่าเป็น UTC เสมอ — ต้องเทียบกับ UTC เท่านั้น ห้ามใช้ local time
    # (เครื่องรันอยู่ timezone อื่น เช่น UTC+7 จะทำให้ diff คลาดเคลื่อนหลายชั่วโมง)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    HEARTBEAT_TIMEOUT = timedelta(minutes=3)
    active_found = False

    teams = []
    for _, run in live_runs.iterrows():
        trades_df = get_trades(settings.log_db_path, run["run_id"])
        open_trades = trades_df[trades_df["exit_time"].isna()] if not trades_df.empty else trades_df
        closed_trades = trades_df[trades_df["exit_time"].notna()] if not trades_df.empty else trades_df

        # เช็ค heartbeat: ถ้า last_heartbeat ยังใหม่ (< 3 นาทีที่ผ่านมา) = still running
        is_running = False
        if pd.notna(run.get("last_heartbeat")):
            try:
                last_hb = pd.to_datetime(run["last_heartbeat"])
                if now - last_hb < HEARTBEAT_TIMEOUT:
                    is_running = True
                    active_found = True
            except (ValueError, TypeError):
                pass

        teams.append({
            "run_id": run["run_id"],
            "strategy": run["strategy"],
            "timeframe": run["timeframe"],
            "started_at": run["started_at"],
            "finished_at": run["finished_at"],
            "last_heartbeat": run.get("last_heartbeat"),
            "is_running": is_running,
            "initial_balance": run["initial_balance"],
            "open_position": _sanitize(open_trades)[0] if not open_trades.empty else None,
            "closed_trades_today": len(closed_trades),
            "total_pnl": round(float(closed_trades["pnl"].sum()), 2) if not closed_trades.empty else 0.0,
            "recent_trades": _sanitize(closed_trades.tail(5)),
        })
    return {"active": active_found, "teams": teams}


@app.get("/runs/{run_id}")
def api_run_detail(run_id: str) -> dict:
    settings = load_settings()
    runs_df = list_runs(settings.log_db_path)
    match = runs_df[runs_df["run_id"] == run_id]
    if match.empty:
        raise HTTPException(status_code=404, detail=f"ไม่พบ run_id={run_id}")
    run = _sanitize(match)[0]

    trades_df = get_trades(settings.log_db_path, run_id)
    trades = _sanitize(trades_df)
    regime_breakdown = _regime_breakdown(trades_df)
    review_summary = aggregate_review_from_rows(trades)

    config = None
    if run.get("config"):
        try:
            config = json.loads(run["config"])
        except (ValueError, TypeError):
            config = None

    rejected_df = get_decisions(settings.log_db_path, run_id, approved=False)
    rejected_reasons = (
        rejected_df["reason"].value_counts().reset_index(name="count").rename(columns={"index": "reason"})
    )
    rejected_reasons.columns = ["reason", "count"]

    return {
        "run": run,
        "trades": trades,
        "rejected_count": int(len(rejected_df)),
        "rejected_reasons": rejected_reasons.to_dict(orient="records"),
        "regime_breakdown": regime_breakdown,
        "review_summary": review_summary,
        "config": config,
    }

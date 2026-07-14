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
        empty_portfolio = {
            "initial_balance": 0.0, "current_balance": 0.0, "total_pnl": 0.0,
            "floating_pnl": 0.0, "equity_curve": [], "pnl_candles": [], "by_team": [],
        }
        return {"active": False, "teams": [], "portfolio": empty_portfolio}

    # ทุกครั้งที่ live_runner ถูก restart จะได้ run_id ใหม่ (มี timestamp ต่อท้าย) ของทีมเดิม —
    # เอาแค่ run ล่าสุดต่อ (strategy, timeframe) เพื่อไม่ให้เห็นทีมซ้ำๆ จากการ restart ที่ผ่านมา
    # (list_runs เรียง started_at DESC มาแล้ว จึงเก็บแถวแรกของแต่ละกลุ่มได้เลย)
    live_runs = live_runs.drop_duplicates(subset=["strategy", "timeframe"], keep="first")

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

        # ปกติแล้วทีมละ 1 ไม้พร้อมกันเท่านั้น (v1 ไม่ pyramiding — ดู process_bar ใน live_runner.py)
        # ถ้ามี >1 แถวที่ exit_time ว่างพร้อมกัน แปลว่ามี race/บั๊กที่ทำให้ DB ไม่ sync กับความจริง
        # ห้ามเลือกแถวแรกแบบเงียบๆ (เคยเป็นต้นเหตุของบั๊กราคาค้าง) ต้อง log ให้เห็นชัดๆ แทน
        if len(open_trades) > 1:
            print(f"[web] คำเตือน: {run['strategy']}:{run['timeframe']} มี {len(open_trades)} ไม้เปิด "
                  f"พร้อมกัน (ควรมีแค่ 1) — โชว์ไม้ล่าสุด ตรวจสอบ DB", flush=True)
            open_trades = open_trades.tail(1)
        open_position = _sanitize(open_trades)[0] if not open_trades.empty else None
        if open_position is not None and open_position.get("margin_used") and run["initial_balance"]:
            open_position["margin_pct"] = round(
                open_position["margin_used"] / float(run["initial_balance"]) * 100, 2
            )
        else:
            if open_position is not None:
                open_position["margin_pct"] = None

        # คำนวณ metric สดจาก trades จริง — live run ไม่มีวัน "จบ" จึงไม่มีทาง finish_run()
        # มาเติม win_rate/profit_factor/balance ใน runs table ให้ได้ ต้องคิดเองตรงนี้ทุกครั้ง
        initial_balance = float(run["initial_balance"] or 0)
        closed_pnls = closed_trades["pnl"].astype(float) if not closed_trades.empty else pd.Series(dtype=float)
        total_closed = len(closed_pnls)
        wins = int((closed_pnls > 0).sum())
        gross_profit = float(closed_pnls[closed_pnls > 0].sum())
        gross_loss = float(abs(closed_pnls[closed_pnls < 0].sum()))
        win_rate_pct = round(wins / total_closed * 100, 1) if total_closed else None
        profit_factor = round(gross_profit / gross_loss, 3) if gross_loss > 0 else (None if gross_profit == 0 else float("inf"))
        if profit_factor == float("inf"):
            profit_factor = None  # ยังไม่เคยแพ้เลย — ยังสรุป PF ไม่ได้ (ไม่ใช่ infinity)
        expectancy = round(float(closed_pnls.mean()), 2) if total_closed else None
        realized_pnl = round(float(closed_pnls.sum()), 2) if total_closed else 0.0
        floating_pnl = float(open_position["floating_pnl"]) if open_position and open_position.get("floating_pnl") is not None else 0.0
        current_balance = round(initial_balance + realized_pnl + floating_pnl, 2)

        # equity curve แบบย่อ (จุดเดียวต่อไม้ที่ปิดแล้ว) ให้ sparkline ในการ์ดใช้ได้เลย ไม่ต้องเรียก /runs/{id} แยก
        equity_curve = []
        if total_closed:
            running = initial_balance
            for _, tr in closed_trades.sort_values("exit_time").iterrows():
                running += float(tr["pnl"])
                equity_curve.append({"time": str(tr["exit_time"]), "balance": round(running, 2)})

        teams.append({
            "run_id": run["run_id"],
            "strategy": run["strategy"],
            "timeframe": run["timeframe"],
            # symbol ต่อทีม (multi-asset) — run เก่าก่อนมีคอลัมน์นี้จะเป็น None ให้ fallback SYMBOL หลัก
            "symbol": run.get("symbol") if pd.notna(run.get("symbol")) else settings.symbol,
            "started_at": run["started_at"],
            "finished_at": run["finished_at"],
            "last_heartbeat": run.get("last_heartbeat"),
            "is_running": is_running,
            "initial_balance": run["initial_balance"],
            "current_balance": current_balance,
            "open_position": open_position,
            "total_trades": total_closed,
            "win_rate_pct": win_rate_pct,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "closed_trades_today": len(closed_trades),
            "total_pnl": realized_pnl,
            "floating_pnl": round(floating_pnl, 2),
            "equity_curve": equity_curve,
            "recent_trades": _sanitize(closed_trades.sort_values("exit_time", ascending=False).head(10)),
            # เก็บไว้เฉพาะประกอบ portfolio รวมด้านล่าง — ไม่ได้ตั้งใจให้ frontend ใช้ตรงๆ
            "_closed_trades": closed_trades,
        })

    # กราฟ equity รวมทั้งพอร์ต — เอาไม้ที่ปิดแล้วของทุกทีมมาเรียงตามเวลาจริง แล้วไล่บวกทีละไม้
    # (เสมือนเงินทุกทีมอยู่ก้อนเดียวกัน) ต่างจาก equity_curve ต่อทีมที่แยกกันคนละเส้น
    #
    # สำคัญ: ทุกทีมแชร์บัญชี MT5 เดียวกันจริงๆ (live_runner.py::run() ดึง account_balance()
    # แค่ครั้งเดียวตอน bootstrap แล้วส่งค่าเดียวกันให้ทุกทีม) ดังนั้น initial_balance ที่เก็บไว้ใน
    # runs table ของแต่ละทีมคือ "เงินก้อนเดียวกัน" ซ้ำกัน 8 ครั้ง — ห้ามเอามาบวกกัน (จะได้ตัวเลข
    # พองเกินจริง 8 เท่า) ต้องใช้ค่าเดียว (ทุกทีมค่าเท่ากันอยู่แล้ว เอาตัวแรกที่ไม่ใช่ 0 มาใช้)
    all_closed = []
    for t in teams:
        for _, tr in t["_closed_trades"].iterrows():
            all_closed.append({"exit_time": tr["exit_time"], "pnl": float(tr["pnl"])})
    all_closed.sort(key=lambda r: r["exit_time"])

    portfolio_initial = round(
        next((float(t["initial_balance"]) for t in teams if t["initial_balance"]), 0.0), 2
    )
    portfolio_running = portfolio_initial
    portfolio_equity_curve = [{"time": "start", "balance": portfolio_initial}]
    for r in all_closed:
        portfolio_running += r["pnl"]
        portfolio_equity_curve.append({"time": str(r["exit_time"]), "balance": round(portfolio_running, 2)})

    # แท่งเทียน (OHLC) ของ balance รวมพอร์ต แบ่งตามชั่วโมงที่มีไม้ปิดจริง — ชั่วโมงไหนไม่มีไม้ปิด
    # ไม่มีแท่ง (ไม่ interpolate) เพราะราคาไม่ได้ขยับต่อเนื่องแบบ tick data ปกติ นี่คือ balance
    # ที่ขยับเป็นขั้นบันไดตอนไม้ปิดเท่านั้น
    pnl_candles = []
    if all_closed:
        running = portfolio_initial
        bucket_key = None
        bucket = None
        for r in all_closed:
            hour_key = pd.Timestamp(r["exit_time"]).floor("h")
            open_before = running
            running += r["pnl"]
            if hour_key != bucket_key:
                if bucket is not None:
                    pnl_candles.append(bucket)
                bucket_key = hour_key
                bucket = {
                    "time": str(hour_key),
                    "open": round(open_before, 2),
                    "high": round(max(open_before, running), 2),
                    "low": round(min(open_before, running), 2),
                    "close": round(running, 2),
                }
            else:
                bucket["high"] = round(max(bucket["high"], running), 2)
                bucket["low"] = round(min(bucket["low"], running), 2)
                bucket["close"] = round(running, 2)
        if bucket is not None:
            pnl_candles.append(bucket)

    total_realized = round(sum(t["total_pnl"] for t in teams), 2)
    total_floating = round(sum(t["floating_pnl"] for t in teams), 2)
    portfolio = {
        "initial_balance": portfolio_initial,
        "current_balance": round(portfolio_initial + total_realized + total_floating, 2),
        "total_pnl": total_realized,
        "floating_pnl": total_floating,
        "equity_curve": portfolio_equity_curve,
        "pnl_candles": pnl_candles,
        "by_team": [
            {
                "strategy": t["strategy"],
                "timeframe": t["timeframe"],
                "symbol": t["symbol"],
                "pnl": round(t["total_pnl"] + t["floating_pnl"], 2),
            }
            for t in teams
        ],
        # สรุปต่อสินทรัพย์ (multi-asset) — ตอนนี้อาจมีแค่ GOLD แต่โครงสร้างรองรับหลายตัวแล้ว
        "by_symbol": [
            {
                "symbol": sym,
                "pnl": round(sum(t["total_pnl"] + t["floating_pnl"] for t in teams if t["symbol"] == sym), 2),
                "teams": sum(1 for t in teams if t["symbol"] == sym),
                "open_positions": sum(1 for t in teams if t["symbol"] == sym and t["open_position"]),
            }
            for sym in sorted({t["symbol"] for t in teams})
        ],
    }
    for t in teams:
        del t["_closed_trades"]

    return {"active": active_found, "teams": teams, "portfolio": portfolio}


@app.get("/live/candles")
def api_live_candles(symbol: str = "GOLD", timeframe: str = "M30", bars: int = 300) -> dict:
    """แท่งเทียนราคาจริง + จุดเข้า/ออกไม้ของทุกทีม (สำหรับกราฟสไตล์ TradingView บนหน้า Live)

    แหล่งราคา: ลอง MT5 สด (เครื่องที่รัน backend มัก login terminal อยู่แล้ว) — ถ้าไม่ได้
    fallback เป็นไฟล์ parquet cache (ราคาจะอัปเดตถึงครั้งล่าสุดที่ดึงข้อมูลเท่านั้น)
    """
    from pathlib import Path

    settings = load_settings()
    bars = max(50, min(bars, 1000))
    df = None
    source = "parquet"
    try:
        import MetaTrader5 as mt5
        tf_map = {"M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15", "M30": "TIMEFRAME_M30",
                  "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4"}
        if timeframe in tf_map and mt5.initialize():
            mt5.symbol_select(symbol, True)
            rates = mt5.copy_rates_from_pos(symbol, getattr(mt5, tf_map[timeframe]), 0, bars)
            if rates is not None and len(rates) > 10:
                df = pd.DataFrame(rates)
                df["time"] = pd.to_datetime(df["time"], unit="s")
                df = df.set_index("time")
                source = "mt5"
    except Exception:
        df = None
    if df is None:
        pq = Path(settings.data_dir) / f"{symbol}_{timeframe}.parquet"
        if not pq.exists():
            raise HTTPException(status_code=404, detail=f"ไม่มีข้อมูล {symbol} {timeframe} (MT5 ไม่ตอบและไม่มี parquet)")
        df = pd.read_parquet(pq).tail(bars)

    candles = [
        {"time": int(ts.timestamp()), "open": float(r["open"]), "high": float(r["high"]),
         "low": float(r["low"]), "close": float(r["close"])}
        for ts, r in df.iterrows()
    ]
    t_start = df.index[0]

    # markers จุดเข้า/ออกของทุกทีม live บน symbol นี้ ภายในช่วงเวลาของกราฟ
    runs_df = list_runs(settings.log_db_path)
    live_runs = runs_df[runs_df["run_id"].str.startswith("live_", na=False)]
    live_runs = live_runs.drop_duplicates(subset=["strategy", "timeframe"], keep="first")
    markers, open_lines = [], []
    for _, run in live_runs.iterrows():
        run_symbol = run.get("symbol") if pd.notna(run.get("symbol")) else settings.symbol
        if run_symbol != symbol:
            continue
        team_label = f"{run['strategy']}:{run['timeframe']}"
        trades_df = get_trades(settings.log_db_path, run["run_id"])
        if trades_df.empty:
            continue
        for _, tr in trades_df.iterrows():
            entry_t = pd.to_datetime(tr["entry_time"])
            if entry_t >= t_start and pd.notna(tr.get("entry")):
                is_buy = tr["direction"] == "BUY"
                markers.append({
                    "time": int(entry_t.timestamp()),
                    "position": "belowBar" if is_buy else "aboveBar",
                    "shape": "arrowUp" if is_buy else "arrowDown",
                    "color": "#22C55E" if is_buy else "#EF4444",
                    "text": f"{'B' if is_buy else 'S'} {team_label}",
                })
            if pd.notna(tr.get("exit_time")):
                exit_t = pd.to_datetime(tr["exit_time"])
                if exit_t >= t_start and pd.notna(tr.get("pnl")):
                    win = float(tr["pnl"]) >= 0
                    markers.append({
                        "time": int(exit_t.timestamp()),
                        "position": "aboveBar" if tr["direction"] == "BUY" else "belowBar",
                        "shape": "circle",
                        "color": "#22C55E" if win else "#EF4444",
                        "text": f"x {float(tr['pnl']):+.0f}",
                    })
            else:
                # ไม้เปิดอยู่ — ส่งเส้น entry/SL/TP ให้กราฟวาดระดับราคา
                open_lines.append({
                    "team": team_label, "direction": tr["direction"],
                    "entry": float(tr["entry"]) if pd.notna(tr.get("entry")) else None,
                    "sl": float(tr["sl"]) if pd.notna(tr.get("sl")) else None,
                    "tp": float(tr["tp"]) if pd.notna(tr.get("tp")) else None,
                })
    markers.sort(key=lambda m: m["time"])
    return {"symbol": symbol, "timeframe": timeframe, "source": source,
            "candles": candles, "markers": markers, "open_lines": open_lines}


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

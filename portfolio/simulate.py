"""Portfolio simulator — ทุกทีมเทรดร่วมกันด้วยเงินก้อนเดียว compounding จริง

หลักการ (Portfolio Thinking ตาม SOP ข้อ 25):
- replay ไม้จริงจาก DB (run ล่าสุดของแต่ละทีม/TF) เรียงตามเวลาเข้าไม้
- ขนาดไม้คำนวณใหม่จาก equity ปัจจุบัน × risk% ของทีม × ตัวคูณ (compounding)
  ทำได้แม่นเพราะ pnl ต่อ 1 lot คงที่: pnl_new = (pnl_เดิม / lot_เดิม) × lot_ใหม่
- กันความเสี่ยงกองรวม: จำกัดไม้เปิดพร้อมกัน + จำกัดไม้ทิศเดียวกัน + daily loss lock ระดับพอร์ต
- ใช้ตอบคำถามตรงๆ ว่า "เป้าผลตอบแทน X%/เดือน ต้องแลกกับ DD เท่าไหร่" ด้วยข้อมูลจริง

ข้อจำกัดที่ต้องรู้: ไม่คิด margin (เลเวอเรจ 1:1000 margin เริ่มมีผลเมื่อ lot ใหญ่มาก),
lot สูงสุดตามโบรกจริง (XM: 50)

correlation_aware=True (ค่าเริ่มต้นปิดไว้ กันพฤติกรรมเปลี่ยนแบบไม่ตั้งใจ): แก้จุดอ่อนที่
max_same_direction จำกัดแค่ "จำนวนไม้ทิศเดียวกัน" ไม่ได้ดูว่าทีมเหล่านั้น correlated กันแค่ไหน —
เช่น trend_pullback (H1) กับ london_breakout (M15) เข้า long พร้อมกันถูกนับเป็น "2 หน่วยกระจายความเสี่ยง"
ทั้งที่จริงอาจเป็น bet ทิศทางเดียวกันเกือบสมบูรณ์ (correlation สูง) ถ้าเปิดใช้ จะคำนวณ correlation
ของ PnL รายวันระหว่างทีม แล้วหด lot ของไม้ใหม่ลงถ้าทีมที่เปิดพร้อมกัน (ทิศเดียวกัน) มี correlation สูง
กับทีมนี้ — ไม่ทำแบบนี้ max_drawdown_pct ที่รายงานจะต่ำกว่าความเป็นจริงเพราะไม่เคยจำลอง joint
price move ระหว่างกลยุทธ์ที่เดิมพันเรื่องเดียวกันจริงๆ
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from persistence.db import get_trades, list_runs
from risk.position_sizing import RiskConfig, RiskManager

CONTRACT_SIZE = 100.0
MIN_CORRELATION_SCALE = 0.3  # กันไม่ให้ correlation สูงมากจนหด lot จนแทบเป็นศูนย์ (ยังต้องเทรดได้)


def _compute_correlation_matrix(trades: pd.DataFrame) -> pd.DataFrame:
    """คำนวณ correlation ของ PnL รายวัน (sum ต่อวัน) ระหว่างแต่ละทีม — ใช้ตัดสินว่าไม้ทิศเดียวกัน
    จากคนละทีมเป็น "ความเสี่ยงเดียวกัน" มากแค่ไหน (correlation สูง = เดิมพันเรื่องเดียวกันจริงๆ)
    """
    daily = (
        trades.assign(exit_date=trades["exit_time"].dt.date)
        .groupby(["exit_date", "team"])["pnl"]
        .sum()
        .unstack("team")
    )
    # ทีมที่ไม่มีไม้ในวันนั้นถือว่า pnl=0 (ไม่ใช่ NaN) กันการเทียบ correlation ผิดเพี้ยนจาก missing data
    daily = daily.fillna(0.0)
    if daily.shape[0] < 3 or daily.shape[1] < 2:
        return pd.DataFrame()  # ข้อมูลไม่พอคำนวณ correlation ที่มีความหมาย
    return daily.corr()


@dataclass
class PortfolioResult:
    initial_balance: float
    final_balance: float
    max_drawdown_pct: float
    taken: int
    skipped_concurrent: int
    skipped_direction: int
    skipped_daily_lock: int
    monthly_returns: list[dict] = field(default_factory=list)  # [{month, return_pct, equity}]
    equity_curve: list[tuple] = field(default_factory=list)
    ruined: bool = False  # equity เคยต่ำกว่า 40% ของทุนไหม (นับว่าเจ๊งในทางปฏิบัติ)


def _load_selection_trades(db_path: str, selections: list[tuple[str, str, float]]) -> pd.DataFrame:
    """selections: [(strategy, timeframe, risk_pct_ต่อไม้ของทีม)] → เทรดทั้งหมดพร้อมข้อมูล replay"""
    runs = list_runs(db_path)
    finished = runs[runs["finished_at"].notna()]
    frames = []
    for strategy, timeframe, risk_pct in selections:
        match = finished[
            (finished["strategy"] == strategy) & (finished["timeframe"] == timeframe)
        ]
        if match.empty:
            raise ValueError(f"ไม่พบ run ของ {strategy} {timeframe} ใน DB")
        run_id = match.iloc[0]["run_id"]
        trades = get_trades(db_path, run_id)
        if trades.empty:
            continue
        trades = trades.copy()
        trades["team"] = f"{strategy}:{timeframe}"
        trades["team_risk_pct"] = risk_pct
        frames.append(trades)
    all_trades = pd.concat(frames, ignore_index=True)
    all_trades["entry_time"] = pd.to_datetime(all_trades["entry_time"])
    all_trades["exit_time"] = pd.to_datetime(all_trades["exit_time"])
    return all_trades


def simulate_portfolio(
    db_path: str,
    selections: list[tuple[str, str, float]],
    initial_balance: float = 10000.0,
    risk_multiplier: float = 1.0,
    max_concurrent: int = 3,
    max_same_direction: int = 2,
    daily_loss_limit_pct: float = 5.0,
    max_lot: float = 50.0,
    min_lot: float = 0.01,
    dd_targeting: bool = False,
    dd_ceiling_pct: float = 20.0,
    dd_budget_headroom: float = 0.5,
    dd_budget_boost_cap: float = 1.15,
    dd_budget_floor: float = 0.6,
    correlation_aware: bool = False,
    min_correlation_scale: float = MIN_CORRELATION_SCALE,
) -> PortfolioResult:
    """dd_targeting: ปรับขนาดไม้ระดับพอร์ตตามพื้นที่ว่างก่อนชน dd_ceiling_pct (เหมือน single-team
    แต่ใช้ drawdown ของ equity รวมทั้งพอร์ต) — boost ตอนห่างเพดาน, หด lot ตอนใกล้เพดาน

    correlation_aware: ถ้า True หด lot ของไม้ใหม่ลงตาม correlation กับทีมที่เปิดไม้ทิศเดียวกันอยู่
    (ดู docstring บนสุดของไฟล์) ค่าเริ่มต้นปิดไว้เพื่อไม่ให้ผลลัพธ์เดิมเปลี่ยนแบบไม่ตั้งใจ
    """
    trades = _load_selection_trades(db_path, selections)
    corr_matrix = _compute_correlation_matrix(trades) if correlation_aware else pd.DataFrame()
    dd_manager = RiskManager(
        RiskConfig(
            max_drawdown_pct=dd_ceiling_pct,
            dd_targeting=dd_targeting,
            dd_budget_headroom=dd_budget_headroom,
            dd_budget_boost_cap=dd_budget_boost_cap,
            dd_budget_floor=dd_budget_floor,
        )
    )

    # หน้าต่างเวลาร่วม: ทุกทีมต้องมีข้อมูลครอบคลุม (กันทีม TF สั้นได้เปรียบ/เสียเปรียบ)
    start = max(trades.groupby("team")["entry_time"].min())
    end = min(trades.groupby("team")["exit_time"].max())
    trades = trades[(trades["entry_time"] >= start) & (trades["exit_time"] <= end)]
    trades = trades.sort_values("entry_time").reset_index(drop=True)

    equity = initial_balance
    peak = equity
    max_dd = 0.0
    open_positions: list[dict] = []  # {exit_time, direction, pnl_scaled}
    curve: list[tuple] = [(start, equity)]
    taken = skipped_concurrent = skipped_direction = skipped_daily = 0
    current_date = None
    day_start_equity = equity
    day_locked = False
    ruined = False

    def settle_until(when) -> None:
        nonlocal equity, peak, max_dd, ruined
        due = sorted(
            [p for p in open_positions if p["exit_time"] <= when], key=lambda p: p["exit_time"]
        )
        for pos in due:
            equity += pos["pnl_scaled"]
            open_positions.remove(pos)
            peak = max(peak, equity)
            dd = (peak - equity) / peak * 100 if peak > 0 else 0
            max_dd = max(max_dd, dd)
            if equity <= initial_balance * 0.4:
                ruined = True
            curve.append((pos["exit_time"], equity))

    for row in trades.itertuples():
        settle_until(row.entry_time)

        if row.entry_time.date() != current_date:
            current_date = row.entry_time.date()
            day_start_equity = equity
            day_locked = False

        if ruined:
            break
        if day_locked or (
            day_start_equity > 0
            and (day_start_equity - equity) / day_start_equity * 100 >= daily_loss_limit_pct
        ):
            day_locked = True
            skipped_daily += 1
            continue
        if len(open_positions) >= max_concurrent:
            skipped_concurrent += 1
            continue
        same_dir_positions = [p for p in open_positions if p["direction"] == row.direction]
        if len(same_dir_positions) >= max_same_direction:
            skipped_direction += 1
            continue

        risk_dist = abs(row.entry - row.sl)
        if risk_dist <= 0 or row.lot <= 0:
            continue
        current_dd_pct = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
        dd_scale = dd_manager.drawdown_budget_scale(current_dd_pct)

        # correlation_aware: หด lot ถ้าทีมที่เปิดไม้ทิศเดียวกันอยู่ตอนนี้ correlated กับทีมนี้สูง
        # (เดิมพันเรื่องเดียวกันจริงๆ ไม่ใช่กระจายความเสี่ยง) — ยิ่ง correlation เฉลี่ยสูง ยิ่งหด lot มาก
        corr_scale = 1.0
        if correlation_aware and same_dir_positions and not corr_matrix.empty and row.team in corr_matrix.columns:
            corrs = [
                corr_matrix.loc[row.team, p["team"]]
                for p in same_dir_positions
                if p["team"] in corr_matrix.columns and not pd.isna(corr_matrix.loc[row.team, p["team"]])
            ]
            if corrs:
                avg_corr = max(0.0, sum(corrs) / len(corrs))  # correlation ติดลบไม่ต้องหด (กระจายจริง)
                corr_scale = max(min_correlation_scale, 1.0 / math.sqrt(1 + avg_corr * len(same_dir_positions)))

        risk_amount = equity * (row.team_risk_pct / 100.0) * risk_multiplier * dd_scale * corr_scale
        lot_new = max(min_lot, min(max_lot, round(risk_amount / (risk_dist * CONTRACT_SIZE), 2)))
        pnl_per_lot = row.pnl / row.lot
        open_positions.append(
            {
                "team": row.team,
                "exit_time": row.exit_time,
                "direction": row.direction,
                "pnl_scaled": pnl_per_lot * lot_new,
            }
        )
        taken += 1

    settle_until(end + pd.Timedelta(days=1))

    # ผลตอบแทนรายเดือน
    curve_series = pd.Series({t: e for t, e in curve}).sort_index()
    monthly_last = curve_series.resample("ME").last().dropna()
    monthly = []
    prev = initial_balance
    for month_end, eq in monthly_last.items():
        monthly.append(
            {
                "month": str(month_end.date())[:7],
                "return_pct": round((eq - prev) / prev * 100, 1) if prev > 0 else 0.0,
                "equity": round(float(eq), 0),
            }
        )
        prev = eq

    return PortfolioResult(
        initial_balance=initial_balance,
        final_balance=round(float(equity), 2),
        max_drawdown_pct=round(max_dd, 2),
        taken=taken,
        skipped_concurrent=skipped_concurrent,
        skipped_direction=skipped_direction,
        skipped_daily_lock=skipped_daily,
        monthly_returns=monthly,
        equity_curve=curve,
        ruined=ruined,
    )

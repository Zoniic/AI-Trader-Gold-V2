"""สภานักวิเคราะห์ AI หลายมุม — วิเคราะห์ผลเทรดของทุกทีมจาก DB คนละแง่มุม แล้วประชุมสรุป

ตอนนี้แต่ละ "นักวิเคราะห์" เป็นกฎที่คำนวณจากข้อมูลจริงตรงๆ (deterministic, ตรวจสอบได้)
ออกแบบ interface ไว้ให้สลับเป็น LLM agent จริงได้ทีหลังโดยไม่กระทบส่วนอื่น — แค่เปลี่ยน
ฟังก์ชัน analyze() ของแต่ละ Analyst ให้เรียก LLM แทนกฎ คนเรียกใช้ (run_council) ไม่ต้องแก้เลย
รันทุกสัปดาห์ตาม SOP ข้อ 6 (Trading Journal ประชุมทุกสัปดาห์) ผ่าน `python run_analysis.py`
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from persistence.db import get_trades, list_runs

AnalyzeFn = Callable[[pd.DataFrame, pd.DataFrame], list[str]]


@dataclass
class Analyst:
    name: str
    focus: str
    analyze: AnalyzeFn  # (runs_df, trades_df ของทุกทีมรวมกัน) -> findings


def _latest_trades_only(runs: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    """กรอง trades ให้เหลือเฉพาะของ run ล่าสุดต่อ (ทีม, TF) — กันรายงานซ้ำจาก run เก่าที่ถูกแทนที่แล้ว"""
    if trades.empty:
        return trades
    latest_run_ids = set(_latest_per_team_tf(runs)["run_id"])
    return trades[trades["run_id"].isin(latest_run_ids)]


def _risk_analyst(runs: pd.DataFrame, trades: pd.DataFrame) -> list[str]:
    trades = _latest_trades_only(runs, trades)
    if trades.empty:
        return ["ยังไม่มีข้อมูลเทรดให้วิเคราะห์"]
    findings = []
    worst_mae = trades[trades["mae_r"].notna()].nlargest(3, "mae_r")
    for row in worst_mae.itertuples():
        findings.append(
            f"[{row.run_id}] ไม้ {row.direction} @ {row.entry:.2f} สวนลึกถึง {row.mae_r:.1f}R "
            f"ก่อนออก ({row.outcome}) — SL อาจกว้างเกินความจำเป็นสำหรับทีมนี้"
        )
    big_losses = trades[trades["pnl_r"] < -1.05]
    if len(big_losses) > 0:
        pct = len(big_losses) / len(trades) * 100
        findings.append(
            f"พบ {len(big_losses)}/{len(trades)} ไม้ ({pct:.1f}%) ขาดทุนเกิน 1R ใน run ล่าสุด "
            "— ปกติมาจาก slippage/cost ไม่ใช่ SL พัง ถ้าสัดส่วนสูงผิดปกติควรตรวจ cost model"
        )
    return findings or ["ไม่พบความเสี่ยงผิดปกติในรอบล่าสุด"]


def _latest_per_team_tf(runs: pd.DataFrame) -> pd.DataFrame:
    finished = runs[runs["finished_at"].notna()].copy()
    finished["timeframe"] = finished["timeframe"].fillna("H1")
    return finished.sort_values("started_at", ascending=False).drop_duplicates(
        subset=["strategy", "timeframe"], keep="first"
    )


def _edge_analyst(runs: pd.DataFrame, trades: pd.DataFrame) -> list[str]:
    latest = _latest_per_team_tf(runs)
    losers = latest[
        (latest["expectancy"] < 0) & (latest["total_trades"].fillna(0) >= 30)
    ].sort_values("expectancy")
    findings = [
        f"{row.strategy} ({row.timeframe}): expectancy {row.expectancy:.2f} ติดลบ "
        f"({int(row.total_trades)} ไม้ล่าสุด) — edge อาจไม่จริง ควรพัก/rework ก่อนเพิ่ม risk"
        for row in losers.itertuples()
    ]
    winners = len(latest) - len(losers)
    findings.append(f"สรุป: {winners}/{len(latest)} (ทีม,TF) ล่าสุด expectancy เป็นบวก")
    return findings


def _discipline_analyst(runs: pd.DataFrame, trades: pd.DataFrame) -> list[str]:
    trades = _latest_trades_only(runs, trades)
    findings = []
    if trades.empty or "discussion" not in trades.columns:
        return ["ยังไม่มีข้อมูลมติทีมให้ตรวจ"]
    import json

    dissent_count = 0
    total_with_discussion = 0
    for raw in trades["discussion"].dropna():
        try:
            opinions = json.loads(raw)
        except (ValueError, TypeError):
            continue
        total_with_discussion += 1
        if any(not o.get("approve", True) for o in opinions):
            dissent_count += 1
    if total_with_discussion > 0:
        pct = dissent_count / total_with_discussion * 100
        findings.append(
            f"{dissent_count}/{total_with_discussion} ไม้ ({pct:.0f}%) เข้าทั้งที่มีเสียงค้านในทีม "
            "— ถ้าไม้กลุ่มนี้แพ้บ่อยกว่าไม้เอกฉันท์ ควรพิจารณาบังคับ min_approvals=5"
        )
    return findings or ["ไม่มีข้อมูลมติให้วิเคราะห์"]


def _psychology_analyst(runs: pd.DataFrame, trades: pd.DataFrame) -> list[str]:
    """มองหาพฤติกรรมแบบ FOMO/revenge/overconfidence ในเชิงสถิติ (ไม่ใช่จิตวิทยาจริงเพราะเป็นบอท
    แต่ตรวจ 'รูปแบบ' ที่มนุษย์เทรดผิดพลาดบ่อย เผื่อ logic ทีมเผลอทำพฤติกรรมเดียวกัน)"""
    trades = _latest_trades_only(runs, trades)
    findings = []
    if trades.empty:
        return ["ยังไม่มีข้อมูล"]
    trades = trades.copy()
    trades["exit_time"] = pd.to_datetime(trades["exit_time"])
    trades = trades.sort_values("exit_time")
    # revenge pattern: ไม้ที่เข้าไม่ถึง 1 ชม.หลังแพ้ไม้ก่อนหน้า (ทีมเดียวกัน)
    per_run = []
    for run_id, group in trades.groupby("run_id"):
        group = group.sort_values("exit_time")
        prev_loss_time = None
        revenge_count = 0
        for row in group.itertuples():
            if prev_loss_time is not None:
                gap_hours = (pd.to_datetime(row.entry_time) - prev_loss_time).total_seconds() / 3600
                if 0 <= gap_hours < 1:
                    revenge_count += 1
            prev_loss_time = pd.to_datetime(row.exit_time) if row.pnl < 0 else None
        if revenge_count >= 5:
            per_run.append((run_id, revenge_count))
    per_run.sort(key=lambda x: -x[1])
    for run_id, count in per_run[:8]:
        findings.append(
            f"[{run_id}] เข้าไม้ใหม่ภายใน 1 ชม.หลังแพ้ {count} ครั้ง "
            "— รูปแบบคล้าย revenge trade พิจารณาเพิ่ม cooldown_bars_after_loss"
        )
    if len(per_run) > 8:
        findings.append(f"...และอีก {len(per_run) - 8} run ที่มีรูปแบบเดียวกัน")
    return findings or ["ไม่พบรูปแบบ revenge-trade ที่ชัดเจนใน run ล่าสุด"]


COUNCIL = [
    Analyst("Risk Analyst", "ความเสี่ยงต่อไม้/SL", _risk_analyst),
    Analyst("Edge Analyst", "ความจริงของ edge", _edge_analyst),
    Analyst("Discipline Analyst", "วินัย/มติทีม", _discipline_analyst),
    Analyst("Psychology Analyst", "รูปแบบพฤติกรรมเสี่ยง", _psychology_analyst),
]


def run_council(db_path: str, min_trades_per_team: int = 15) -> dict:
    """เรียกนักวิเคราะห์ทุกคนวิเคราะห์ข้อมูลชุดเดียวกัน แล้วรวมเป็นรายงานเดียว"""
    runs = list_runs(db_path)
    finished = runs[runs["finished_at"].notna()]
    frames = []
    for row in finished.itertuples():
        t = get_trades(db_path, row.run_id)
        if not t.empty:
            t = t.copy()
            t["run_id"] = row.run_id
            frames.append(t)
    all_trades = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    report = {}
    for analyst in COUNCIL:
        report[analyst.name] = {
            "focus": analyst.focus,
            "findings": analyst.analyze(finished, all_trades),
        }
    return report

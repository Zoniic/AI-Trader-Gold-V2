"""Pre-trade context — เช็คลิสต์กลางที่ทุกทีมต้องรู้ก่อนเข้าไม้ (firm-wide pre-trade desk)

ปรัชญา: ไม่ว่าทีมไหนจะเห็น setup ของตัวเอง ก่อนกดเข้าไม้จริงต้องผ่าน "โต๊ะความเสี่ยงกลาง"
ที่ประเมินบริบทตลาด 17 ข้อตามที่ผู้ใช้กำหนด แล้วให้คำแนะนำว่า "ควร skip ไหม"

สำคัญ — แบ่งชัดเป็น 2 กลุ่ม:
[คำนวณได้จาก GOLD OHLCV จริง]  trend, market_speed, atr_level, volume_state, fib_proximity,
    rr, session, gold_overextended, reward_quality, skip_recommended
[ต้องมี data feed ภายนอกที่ระบบยังไม่มี → คืน None + เหตุผล ไม่ใช่เดามั่ว]
    liquidity, order_block, fair_value_gap, news_minutes, dxy_corr, us10y_corr, dollar_strength

ทำไมกลุ่มหลังถึงเป็น None: ระบบโหลดแค่ GOLD ทีละ TF ไม่มี DXY/US10Y feed, ไม่มี news calendar,
และ Liquidity/OB/FVG แบบสถาบันต้องมี market-microstructure engine แยก (ทำลวกๆ = สัญญาณหลอก)
— ระบุไว้ตรงๆ เพื่อไม่ให้เข้าใจผิดว่าบอทเห็นข้อมูลที่จริงๆ มันไม่เห็น
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core.fib_engine import (
    active_leg,
    classify_trend,
    detect_swings,
    fib_retracement_levels,
    fib_zone_hit,
)
from core.signal import Direction

EXTERNAL_UNAVAILABLE = "ต้องมี data feed ภายนอก (ยังไม่ต่อเข้าระบบ)"


@dataclass
class PreTradeContext:
    # --- คำนวณได้จริง ---
    trend: str = "unknown"          # up | down | sideway
    market_speed: str = "normal"    # fast | normal | slow (จาก range ล่าสุด/ATR)
    atr_level: str = "normal"       # high | normal | low (ATR ปัจจุบัน/median)
    atr_ratio: float = 1.0
    volume_state: str = "unknown"   # high | normal | low (vs average)
    fib_proximity: float | None = None   # ราคาห่างระดับ fib ที่ใกล้สุดกี่ ATR (None = ไม่มีแกน)
    fib_level: float | None = None
    rr: float = 0.0
    reward_quality: str = "poor"    # good | ok | poor (จาก rr)
    session: str = "off"            # asia | london | ny | overlap | off
    gold_overextended: bool = False # ราคาเบี่ยงจาก EMA/VWAP เกิน threshold
    overext_atr: float = 0.0
    skip_recommended: bool = False
    skip_reasons: list[str] = field(default_factory=list)
    quality_score: float = 0.0      # 0-100 รวมทุกข้อที่คำนวณได้
    # --- ต้องมี data ภายนอก (None = ระบบยังไม่รู้จริง) ---
    liquidity: None = None
    order_block: None = None
    fair_value_gap: None = None
    news_minutes: None = None
    dxy_corr: None = None
    us10y_corr: None = None
    dollar_strength: None = None
    external_note: str = EXTERNAL_UNAVAILABLE


def _session_of(hour: int) -> str:
    """เวลาโบรก GMT+2/+3 โดยประมาณ"""
    if 1 <= hour < 8:
        return "asia"
    if 9 <= hour < 13:
        return "london"
    if 13 <= hour < 16:
        return "overlap"  # London+NY
    if 16 <= hour < 21:
        return "ny"
    return "off"


def compute_pre_trade_context(
    window: pd.DataFrame,
    direction: Direction,
    entry: float,
    sl: float,
    tp: float,
    atr: float,
    atr_median: float,
    *,
    min_rr: float = 1.3,
    overext_atr_threshold: float = 3.0,
    fast_speed_ratio: float = 1.5,
    slow_speed_ratio: float = 0.6,
    volume_lookback: int = 20,
    swing_order: int = 3,
) -> PreTradeContext:
    ctx = PreTradeContext()
    close = window["close"]

    # 1. Trend
    swings = detect_swings(window, order=swing_order)
    ctx.trend = classify_trend(swings)

    # 2. Market speed — range ของแท่งล่าสุดเทียบ ATR
    last_range = float(window["high"].iloc[-1] - window["low"].iloc[-1])
    speed_ratio = last_range / atr if atr > 0 else 1.0
    ctx.market_speed = "fast" if speed_ratio >= fast_speed_ratio else (
        "slow" if speed_ratio <= slow_speed_ratio else "normal"
    )

    # 3. ATR level เทียบ median
    ctx.atr_ratio = atr / atr_median if atr_median > 0 else 1.0
    ctx.atr_level = "high" if ctx.atr_ratio >= 1.5 else ("low" if ctx.atr_ratio <= 0.6 else "normal")

    # 4. Volume
    if "volume" in window.columns:
        vol_avg = float(window["volume"].tail(volume_lookback).mean())
        vol_now = float(window["volume"].iloc[-1])
        if vol_avg > 0:
            ratio = vol_now / vol_avg
            ctx.volume_state = "high" if ratio >= 1.3 else ("low" if ratio <= 0.7 else "normal")

    # 5. Fib proximity — ราคาปัจจุบันใกล้ระดับ fib retracement ของขาล่าสุดแค่ไหน
    trend_for_fib = ctx.trend if ctx.trend in ("up", "down") else None
    if trend_for_fib:
        leg = active_leg(swings, trend_for_fib)
        if leg is not None:
            lo, hi = leg
            levels = fib_retracement_levels(lo.price, hi.price, trend_for_fib)
            hit = fib_zone_hit(entry, levels, zone_width=atr)  # โซนกว้าง 1 ATR
            if hit is not None:
                ctx.fib_level = hit[1]
                ctx.fib_proximity = abs(entry - hit[1]) / atr if atr > 0 else None

    # 9. RR + reward quality
    risk = abs(entry - sl)
    ctx.rr = abs(tp - entry) / risk if risk > 0 else 0.0
    ctx.reward_quality = "good" if ctx.rr >= 2.0 else ("ok" if ctx.rr >= min_rr else "poor")

    # 10. Session
    ctx.session = _session_of(window.index[-1].hour)

    # 14. Gold overextended — ราคาเบี่ยงจาก EMA50 กี่ ATR
    ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
    ctx.overext_atr = abs(entry - ema50) / atr if atr > 0 else 0.0
    ctx.gold_overextended = ctx.overext_atr >= overext_atr_threshold

    # --- รวม skip decision + quality score (เฉพาะข้อที่คำนวณได้) ---
    reasons: list[str] = []
    score = 0.0

    if ctx.trend in ("up", "down"):
        score += 20
    else:
        reasons.append("โครงสร้าง sideway ไม่ชัดทิศ")

    if ctx.market_speed == "fast" and ctx.atr_level == "high":
        reasons.append("ตลาดเร็ว+ATR สูงพร้อมกัน (มักช่วงข่าว/ผันผวนรุนแรง)")
    else:
        score += 15

    if ctx.reward_quality == "good":
        score += 25
    elif ctx.reward_quality == "ok":
        score += 12
    else:
        reasons.append(f"RR {ctx.rr:.2f} ต่ำกว่าเกณฑ์ {min_rr}")

    if ctx.gold_overextended:
        reasons.append(f"ราคยืดเกิน ({ctx.overext_atr:.1f} ATR จาก EMA50) เสี่ยงย่อแรง")
    else:
        score += 15

    if ctx.volume_state == "high":
        score += 10
    elif ctx.volume_state == "low":
        reasons.append("volume ต่ำ (สภาพคล่องเบา แท่งอาจหลอก)")
    else:
        score += 5

    if ctx.session in ("london", "overlap", "ny"):
        score += 15
    else:
        reasons.append(f"session {ctx.session} (นอกช่วงสภาพคล่องหลัก)")

    ctx.quality_score = score
    # skip เมื่อมีธงแดง "หนัก" อย่างน้อย 1 (overextended หรือ fast+high-ATR) หรือ RR ไม่ถึง
    hard_flags = ctx.gold_overextended or (ctx.market_speed == "fast" and ctx.atr_level == "high") \
        or ctx.reward_quality == "poor"
    ctx.skip_recommended = hard_flags
    ctx.skip_reasons = reasons
    return ctx


def context_to_dict(ctx: PreTradeContext) -> dict:
    """แปลงเป็น dict สำหรับใส่ใน committee ctx / log — external fields คง None ไว้ให้เห็นชัด"""
    return {
        "pt_trend": ctx.trend,
        "pt_market_speed": ctx.market_speed,
        "pt_atr_level": ctx.atr_level,
        "pt_atr_ratio": round(ctx.atr_ratio, 2),
        "pt_volume_state": ctx.volume_state,
        "pt_fib_proximity": None if ctx.fib_proximity is None else round(ctx.fib_proximity, 2),
        "pt_rr": round(ctx.rr, 2),
        "pt_reward_quality": ctx.reward_quality,
        "pt_session": ctx.session,
        "pt_gold_overextended": ctx.gold_overextended,
        "pt_quality_score": round(ctx.quality_score, 0),
        "pt_skip_recommended": ctx.skip_recommended,
        "pt_skip_reasons": ctx.skip_reasons,
        "pt_external_unavailable": [
            "liquidity", "order_block", "fair_value_gap", "news_minutes",
            "dxy_corr", "us10y_corr", "dollar_strength",
        ],
    }

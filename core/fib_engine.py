"""Fibonacci confluence — swing detection, retracement/extension zones, price-action patterns

ใช้ร่วมกับ strategies/fibonacci_confluence.py ตัวไฟล์นี้แยกออกมาให้เทสต์ตรงๆ ได้โดยไม่ต้อง
ผ่าน engine ทั้งชุด — ทุกฟังก์ชันคำนวณจาก DataFrame ที่ส่งเข้ามาเท่านั้น (caller ต้องตัด window
ให้ไม่มองอนาคตเกิน idx เอง เหมือนกลยุทธ์อื่นทุกตัวในระบบ)

ขอบเขตที่ตั้งใจตัดออก (ไม่ทำในรอบนี้ — ระบบยังไม่มีโครงสร้างรองรับให้ทำถูกต้อง):
- Order Block / Fair Value Gap / Liquidity Sweep / BOS / CHOCH แบบ microstructure เต็มรูป
  (ต้องมี market-structure engine แยกที่ซับซ้อนกว่านี้ ทำแบบลวกๆ จะให้ผลข่าวลือมากกว่าของจริง)
- Multi-timeframe จริง (H4→H1→M15→M5) — ระบบตอนนี้โหลดทีละ TF เดียว (H1/M30/M15) ไม่มี H4/M5
  จึงจำลอง "higher-scale confluence" ด้วย swing order ที่กว้างกว่าบน TF เดียวกันแทน (Step 9/10
  ในสเปกต้นฉบับใช้ TF จริงหลายอัน — อันนี้เป็น proxy ไม่ใช่ของแท้ ต้องบอกตรงๆ)
- News filter อัตโนมัติ — ยังไม่มี news calendar ต่อเข้าระบบ (ดู SOP.md ข้อ 15: ตอนนี้เป็น manual)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

FIB_RETRACEMENT_WEIGHTS = {
    0.236: 5.0,
    0.382: 12.0,
    0.5: 15.0,
    0.618: 20.0,
    0.786: 10.0,
}
FIB_EXTENSION_RATIOS = (1.272, 1.618, 2.618)


@dataclass(frozen=True)
class Swing:
    idx: int  # ตำแหน่งใน window ที่ส่งเข้ามา (ไม่ใช่ index ของ df เต็ม)
    price: float
    kind: str  # "high" | "low"


def detect_swings(df: pd.DataFrame, order: int = 3) -> list[Swing]:
    """หา fractal pivot: high/low ที่สูง/ต่ำสุดเทียบกับ `order` แท่งก่อนหน้าและหลัง

    ปลอดภัยจาก lookahead ตราบใดที่ caller ตัด window มาไม่เกิน idx ปัจจุบัน — pivot ตัวสุดท้าย
    ที่ยืนยันได้จะอยู่ที่ตำแหน่ง len(df)-1-order เป็นอย่างน้อย (ต้องมี `order` แท่งหลังมันในกรอบ
    เดียวกัน ซึ่งทั้งหมดเป็นอดีตของ idx อยู่แล้ว)
    """
    highs, lows = df["high"].to_numpy(), df["low"].to_numpy()
    n = len(df)
    swings: list[Swing] = []
    for i in range(order, n - order):
        window_high = highs[i - order : i + order + 1]
        window_low = lows[i - order : i + order + 1]
        if highs[i] == window_high.max() and (window_high == highs[i]).sum() == 1:
            swings.append(Swing(i, float(highs[i]), "high"))
        elif lows[i] == window_low.min() and (window_low == lows[i]).sum() == 1:
            swings.append(Swing(i, float(lows[i]), "low"))
    return swings


def classify_trend(swings: list[Swing]) -> str:
    """ดูจาก swing high/low ล่าสุดสองคู่ — HH+HL=up, LH+LL=down, อย่างอื่น=sideway"""
    highs = [s for s in swings if s.kind == "high"]
    lows = [s for s in swings if s.kind == "low"]
    if len(highs) < 2 or len(lows) < 2:
        return "sideway"
    higher_high = highs[-1].price > highs[-2].price
    higher_low = lows[-1].price > lows[-2].price
    lower_high = highs[-1].price < highs[-2].price
    lower_low = lows[-1].price < lows[-2].price
    if higher_high and higher_low:
        return "up"
    if lower_high and lower_low:
        return "down"
    return "sideway"


def active_leg(swings: list[Swing], trend: str) -> tuple[Swing, Swing] | None:
    """หาแกน fib ที่จะวาด: uptrend ใช้ (low ล่าสุดก่อน high ล่าสุด) -> high ล่าสุด, downtrend กลับกัน"""
    if trend == "up":
        highs = [s for s in swings if s.kind == "high"]
        if not highs:
            return None
        anchor_high = highs[-1]
        lows_before = [s for s in swings if s.kind == "low" and s.idx < anchor_high.idx]
        if not lows_before:
            return None
        return lows_before[-1], anchor_high
    if trend == "down":
        lows = [s for s in swings if s.kind == "low"]
        if not lows:
            return None
        anchor_low = lows[-1]
        highs_before = [s for s in swings if s.kind == "high" and s.idx < anchor_low.idx]
        if not highs_before:
            return None
        return anchor_low, highs_before[-1]
    return None


def fib_retracement_levels(swing_low: float, swing_high: float, trend: str) -> dict[float, float]:
    """โซนย่อ (pullback) ที่คาดว่าราคาจะกลับมาเด้ง — uptrend นับจากบนลงมา, downtrend นับจากล่างขึ้นไป"""
    rng = swing_high - swing_low
    if trend == "up":
        return {r: swing_high - rng * r for r in FIB_RETRACEMENT_WEIGHTS}
    return {r: swing_low + rng * r for r in FIB_RETRACEMENT_WEIGHTS}


def fib_extension_levels(swing_low: float, swing_high: float, trend: str) -> dict[float, float]:
    """เป้ากำไรเลยจุด swing เดิม — uptrend ยิงขึ้นเหนือ swing_high, downtrend ยิงลงใต้ swing_low"""
    rng = swing_high - swing_low
    if trend == "up":
        return {r: swing_low + rng * r for r in FIB_EXTENSION_RATIOS}
    return {r: swing_high - rng * r for r in FIB_EXTENSION_RATIOS}


def fib_zone_hit(
    price: float, levels: dict[float, float], zone_width: float
) -> tuple[float, float] | None:
    """เช็คว่าราคาปัจจุบันอยู่ในโซน ±zone_width ของระดับ fib ไหนไหม — คืน (ratio, ราคาที่ระดับนั้น)
    ถ้าเข้าหลายโซนพร้อมกัน (ซ้อนทับ) เลือกอันน้ำหนักสูงสุด (61.8 > 50 > ...) ตาม Step 4/10"""
    hits = [(r, lv) for r, lv in levels.items() if abs(price - lv) <= zone_width]
    if not hits:
        return None
    return max(hits, key=lambda h: FIB_RETRACEMENT_WEIGHTS.get(h[0], 0.0))


def is_bullish_engulfing(df: pd.DataFrame, i: int) -> bool:
    if i < 1:
        return False
    prev_o, prev_c = df["open"].iloc[i - 1], df["close"].iloc[i - 1]
    o, c = df["open"].iloc[i], df["close"].iloc[i]
    return prev_c < prev_o and c > o and c >= prev_o and o <= prev_c


def is_bearish_engulfing(df: pd.DataFrame, i: int) -> bool:
    if i < 1:
        return False
    prev_o, prev_c = df["open"].iloc[i - 1], df["close"].iloc[i - 1]
    o, c = df["open"].iloc[i], df["close"].iloc[i]
    return prev_c > prev_o and c < o and c <= prev_o and o >= prev_c


def is_pin_bar(df: pd.DataFrame, i: int, direction_sign: int) -> bool:
    """direction_sign +1 = หา hammer (ไส้ล่างยาว, ตัวเทียนเล็ก, ปิดครึ่งบน) สำหรับ BUY
    direction_sign -1 = หา shooting star (ไส้บนยาว, ปิดครึ่งล่าง) สำหรับ SELL"""
    o, h, l, c = df["open"].iloc[i], df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i]
    rng = h - l
    if rng <= 0:
        return False
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    if direction_sign > 0:
        return lower_wick >= body * 2 and lower_wick >= rng * 0.5 and upper_wick <= rng * 0.15
    return upper_wick >= body * 2 and upper_wick >= rng * 0.5 and lower_wick <= rng * 0.15


def price_action_confirmation(
    df: pd.DataFrame, direction_sign: int, zone_low: float, zone_high: float, max_bars: int
) -> tuple[bool, str, int] | tuple[bool, None, None]:
    """เช็ค `max_bars` แท่งล่าสุดว่ามีแท่งยืนยัน (engulfing/pin bar) ที่ตัวแท่งแตะโซน fib ไหม
    คืน (พบไหม, ชื่อ pattern, กี่แท่งที่แล้ว) — ตาม Step 6 ห้ามเข้าทันทีที่แตะ fib ต้องรอ confirm"""
    n = len(df)
    for bars_ago in range(max_bars):
        i = n - 1 - bars_ago
        if i < 1:
            break
        touched = df["low"].iloc[i] <= zone_high and df["high"].iloc[i] >= zone_low
        if not touched:
            continue
        if direction_sign > 0:
            if is_bullish_engulfing(df, i):
                return True, "bullish_engulfing", bars_ago
            if is_pin_bar(df, i, 1):
                return True, "hammer", bars_ago
        else:
            if is_bearish_engulfing(df, i):
                return True, "bearish_engulfing", bars_ago
            if is_pin_bar(df, i, -1):
                return True, "shooting_star", bars_ago
    return False, None, None

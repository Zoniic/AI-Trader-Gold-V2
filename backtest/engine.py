"""วน backtest ทีละแท่งเทียนแบบไม่มี lookahead: evaluate -> เปิดเทรด -> จำลองถือจนออก

จุดออกจัดการโดย _simulate_trade ซึ่งรองรับ trade management:
- partial TP: ปิดบางส่วนเมื่อกำไรถึง X R แล้วเลื่อน SL ไป breakeven (เปิด/ปิดได้ผ่าน config)
- track MAE/MFE ทุกแท่ง เพื่อให้ระบบรีวิว (backtest/review.py) วิเคราะห์ได้ว่า SL/TP ควรปรับยังไง
- post_exit_r: หลังชน TP แอบดูต่ออีก 20 แท่งว่าราคาวิ่งต่อไหม (ใช้วิเคราะห์ย้อนหลังเท่านั้น
  ไม่มีผลต่อการตัดสินใจเทรดใดๆ จึงไม่ใช่ lookahead bias ของผลเทรด)
กติกาแท่งกำกวม (แตะทั้ง SL และ TP ในแท่งเดียว): นับ SL ก่อนเสมอ — ประเมินแบบระมัดระวังสุด
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import pandas as pd

from backtest.costs import CostModel
from backtest.regime import compute_regime
from backtest.review import review_trade, score_trade
from core.signal import Direction, MarketData, Signal
from core.strategy import Strategy
from persistence.db import RunLogger
from risk.live_gate import GateState, check_gate, on_trade_closed, roll_calendar
from risk.position_sizing import RiskConfig, RiskManager

POST_EXIT_LOOKAHEAD_BARS = 20


@dataclass(frozen=True)
class TradeManagement:
    """นโยบายบริหารไม้หลังเข้า — ตั้งต่อทีมได้ใน configs/<team>.json"""

    partial_tp_r: float | None = None  # ปิดบางส่วนเมื่อกำไรถึงกี่ R (None = ไม่ใช้)
    partial_fraction: float = 0.5  # ปิดสัดส่วนเท่าไหร่ของไม้
    move_sl_to_breakeven: bool = True  # หลัง partial แล้วเลื่อน SL ไปราคาเข้าไหม
    trailing_stop_r: float | None = None  # ระยะลาก SL ตามหลังจุดสูงสุด (หน่วย R, None = ไม่ใช้)
    trailing_activate_r: float = 1.0  # เริ่มลากเมื่อกำไรถึงกี่ R
    remove_tp_when_trailing: bool = False  # พอ trailing ทำงานแล้ว ยกเลิก TP ให้ไม้วิ่งไกลสุด (snowball)
    cooldown_bars_after_loss: int = 0  # แพ้แล้วห้ามเข้าไม้ใหม่กี่แท่ง (กัน revenge trade แบบบอท)


@dataclass
class Trade:
    direction: Direction
    entry_time: pd.Timestamp
    entry: float
    sl: float
    tp: float
    lot: float
    exit_time: pd.Timestamp | None = None
    exit_price: float = 0.0  # ราคาออกถัวเฉลี่ยถ่วงน้ำหนัก (กรณีปิดหลายส่วน)
    pnl: float = 0.0
    outcome: str = ""  # tp / sl / tp_after_partial / be_after_partial / timeout / end_of_data
    regime: str = ""
    pnl_r: float = 0.0  # กำไรจริงเป็นเท่าของความเสี่ยงที่ตั้งไว้ (หลังหักต้นทุน)
    mae_r: float = 0.0  # สวนลึกสุดกี่ R ระหว่างถือ
    mfe_r: float = 0.0  # เป็นใจไกลสุดกี่ R ระหว่างถือ
    post_exit_r: float | None = None  # ชน TP แล้วราคาวิ่งต่ออีกกี่ R (วิเคราะห์ย้อนหลัง)
    review: str = ""  # บทวิเคราะห์รายไม้จาก backtest/review.py


@dataclass
class BacktestResult:
    strategy_name: str
    trades: list[Trade] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=pd.Series)
    halted_at: pd.Timestamp | None = None
    halt_reason: str = ""


def _simulate_trade(
    df: pd.DataFrame,
    start_idx: int,
    direction: Direction,
    entry: float,
    sl: float,
    tp: float,
    max_hold: int,
    management: TradeManagement,
) -> tuple[int, list[tuple[float, float]], str, float, float]:
    """เดินทีละแท่งจาก start_idx จนออกครบทั้งไม้

    คืน (exit_idx, parts[(fraction, exit_price)], outcome, mae_r, mfe_r)
    """
    sign = direction.sign
    risk_dist = abs(entry - sl)
    end_idx = min(start_idx + max_hold, len(df) - 1)

    current_sl = sl
    partial_done = False
    trail_active = False
    trail_moved = False
    remaining = 1.0
    parts: list[tuple[float, float]] = []
    mae = 0.0
    mfe = 0.0
    extreme = entry  # ราคาที่เป็นใจสุดที่เคยเห็น ใช้ลาก trailing SL
    partial_level = (
        entry + sign * risk_dist * management.partial_tp_r
        if management.partial_tp_r is not None
        else None
    )
    trail_dist = (
        risk_dist * management.trailing_stop_r if management.trailing_stop_r is not None else None
    )
    activate_level = entry + sign * risk_dist * management.trailing_activate_r

    def _exit_outcome() -> str:
        if trail_moved and (current_sl - entry) * sign > 0:
            return "trailing_stop"
        if partial_done and current_sl == entry:
            return "be_after_partial"
        return "sl"

    for i in range(start_idx, end_idx + 1):
        bar = df.iloc[i]
        high, low = float(bar["high"]), float(bar["low"])
        favorable = (high - entry) if sign > 0 else (entry - low)
        adverse = (entry - low) if sign > 0 else (high - entry)
        mfe = max(mfe, favorable)
        mae = max(mae, adverse)

        # 1) SL ก่อนเสมอ (ระมัดระวังสุดกรณีแท่งเดียวแตะหลายระดับ)
        sl_hit = low <= current_sl if sign > 0 else high >= current_sl
        if sl_hit:
            parts.append((remaining, current_sl))
            return i, parts, _exit_outcome(), mae / risk_dist, mfe / risk_dist

        # 2) partial TP (ครั้งเดียว)
        if partial_level is not None and not partial_done:
            partial_hit = high >= partial_level if sign > 0 else low <= partial_level
            if partial_hit:
                parts.append((management.partial_fraction, partial_level))
                remaining -= management.partial_fraction
                partial_done = True
                if management.move_sl_to_breakeven:
                    current_sl = entry

        # 3) TP เต็ม (ยกเว้นโหมด snowball ที่ตัด TP ทิ้งหลัง trailing ทำงาน)
        if not (management.remove_tp_when_trailing and trail_active):
            tp_hit = high >= tp if sign > 0 else low <= tp
            if tp_hit:
                parts.append((remaining, tp))
                outcome = "tp_after_partial" if partial_done else "tp"
                return i, parts, outcome, mae / risk_dist, mfe / risk_dist

        # 4) อัปเดต trailing SL "หลัง" เช็คทางออกทั้งหมด — มีผลตั้งแต่แท่งถัดไป
        #    (กันความกำกวม intrabar: ห้ามใช้ high แท่งนี้เลื่อน SL แล้วอ้างว่าโดน SL ใหม่ในแท่งเดียวกัน)
        if trail_dist is not None:
            extreme = max(extreme, high) if sign > 0 else min(extreme, low)
            reached_activation = (extreme - activate_level) * sign >= 0
            if reached_activation:
                trail_active = True
                candidate_sl = extreme - sign * trail_dist
                if (candidate_sl - current_sl) * sign > 0:
                    current_sl = candidate_sl
                    trail_moved = True

    close_price = float(df.iloc[end_idx]["close"])
    parts.append((remaining, close_price))
    outcome = "end_of_data" if end_idx == len(df) - 1 else "timeout"
    return end_idx, parts, outcome, mae / risk_dist, mfe / risk_dist


def _confirm_entry(
    df: pd.DataFrame, signal_idx: int, direction: Direction, entry: float, sl: float,
    confirm_bars: int, threshold_r: float,
) -> tuple[int, float] | None:
    """ไม้กระดาษ (paper trade) ยืนยันทิศก่อนเข้าจริง — ดูไปข้างหน้าไม่เกิน confirm_bars แท่ง

    คืน (entry_idx, entry_price) เมื่อราคาไปทางเรา ≥ threshold_r×R ก่อนชน virtual SL
    คืน None เมื่อ: ชน SL ก่อน (สัญญาณหลอก) หรือครบ K แท่งยังไม่ confirm (โมเมนตัมไม่มา)

    ไม่ lookahead: การตัดสินใจเข้าเกิดที่แท่ง j โดยใช้ราคาปิดของแท่ง j เท่านั้น (causal)
    """
    risk_dist = abs(entry - sl)
    if risk_dist <= 0:
        return None
    target = entry + direction.sign * threshold_r * risk_dist
    for j in range(signal_idx + 1, min(signal_idx + 1 + confirm_bars, len(df))):
        hi, lo, cl = float(df["high"].iloc[j]), float(df["low"].iloc[j]), float(df["close"].iloc[j])
        # ชน virtual SL ก่อน = สัญญาณหลอก ยกเลิก (เช็ค SL ก่อน = ระมัดระวังสุด)
        if direction == Direction.BUY and lo <= sl:
            return None
        if direction == Direction.SELL and hi >= sl:
            return None
        # ยืนยัน: ราคาปิดผ่าน threshold ไปทางเรา
        if direction == Direction.BUY and cl >= target:
            return j, cl
        if direction == Direction.SELL and cl <= target:
            return j, cl
    return None


def _post_exit_run(
    df: pd.DataFrame, exit_idx: int, direction: Direction, tp: float, risk_dist: float
) -> float | None:
    """หลังชน TP ราคาวิ่ง "ต่อ" อีกกี่ R ใน 20 แท่งถัดไป — ใช้วิเคราะห์ย้อนหลังเท่านั้น"""
    after = df.iloc[exit_idx + 1 : exit_idx + 1 + POST_EXIT_LOOKAHEAD_BARS]
    if after.empty or risk_dist <= 0:
        return None
    if direction == Direction.BUY:
        further = float(after["high"].max()) - tp
    else:
        further = tp - float(after["low"].min())
    return max(0.0, further) / risk_dist


def run_backtest(
    strategy: Strategy,
    data: MarketData,
    risk_cfg: RiskConfig,
    cost: CostModel,
    warmup: int | None = None,
    max_hold: int = 100,
    logger: RunLogger | None = None,
    management: TradeManagement | None = None,
    allowed_regimes: list[str] | None = None,
    pre_trade_gate: bool = False,
    pre_trade_min_quality: float = 0.0,
    disable_dd_halt: bool = False,
    entry_confirm_bars: int = 0,
    entry_confirm_threshold_r: float = 0.3,
    blocked_hours: list[int] | None = None,
) -> BacktestResult:
    """allowed_regimes: จำกัดทีมให้เทรดเฉพาะสภาวะตลาดที่ตัวเองถนัด (None = เทรดทุกสภาวะ)

    regime ของแต่ละแท่งคำนวณจากข้อมูลย้อนหลังเท่านั้น (backtest/regime.py) จึงใช้เป็น
    ตัวกรอง ณ เวลาจริงได้โดยไม่ lookahead

    pre_trade_gate: เปิดโต๊ะความเสี่ยงกลาง (core/market_context) ประเมินบริบท 17 ข้อก่อนทุกไม้
        — ข้ามไม้เมื่อ skip_recommended=True หรือ quality_score < pre_trade_min_quality
    disable_dd_halt: True = ไม่หยุดเทรดถาวรแม้ DD เกินเพดาน (ใช้ทดสอบว่า kill-switch ช่วยจริงไหม)
    """
    from core.market_context import compute_pre_trade_context
    df = data.df
    warmup = warmup if warmup is not None else getattr(strategy, "min_lookback", lambda: 60)()
    management = management or TradeManagement()
    regime_series = compute_regime(df)
    allowed = set(allowed_regimes) if allowed_regimes else None
    blocked_hr = set(blocked_hours) if blocked_hours else None

    # ATR series สำหรับ vol_scaled sizing (คำนวณครั้งเดียว rolling — ไม่มี lookahead)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr_series = tr.rolling(14).mean()
    atr_median_series = atr_series.rolling(500, min_periods=50).median()

    risk = RiskManager(risk_cfg)
    state = GateState(balance=risk_cfg.account_balance)

    trades: list[Trade] = []
    balance_points: list[tuple[pd.Timestamp, float]] = [(df.index[0], state.balance)]
    halted_at: pd.Timestamp | None = None
    halt_reason = ""

    i = warmup
    while i < len(df) - 1:
        bar_time = df.index[i]
        roll_calendar(state, bar_time)

        gate = check_gate(
            state, risk, risk_cfg, i, bar_time,
            regime=regime_series.iloc[i], allowed_regimes=allowed,
            blocked_hours=blocked_hr, disable_dd_halt=disable_dd_halt,
        )
        if gate.halted:
            halted_at = bar_time
            halt_reason = gate.reason
            remaining_bars = len(df) - 1 - i
            print(
                f"[engine] kill-switch ทำงาน ที่ {halted_at}: {halt_reason} "
                f"— หยุดเทรดถาวรตลอดที่เหลือ ({remaining_bars} แท่งที่ไม่ได้ใช้)"
            )
            break
        if not gate.ok:
            i += 1
            continue

        signal: Signal = strategy.evaluate(data, i)
        if not signal.is_actionable:
            i += 1
            continue

        # ไม้กระดาษยืนยันทิศก่อนเข้าจริง (paper/confirmation entry) — เข้าเมื่อโมเมนตัมพิสูจน์ตัวแล้ว
        entry_idx = i  # แท่งที่เข้าจริง (default = แท่งสัญญาณ)
        if entry_confirm_bars > 0:
            confirmed = _confirm_entry(
                df, i, signal.direction, signal.entry, signal.sl,
                entry_confirm_bars, entry_confirm_threshold_r,
            )
            if confirmed is None:
                i += 1
                continue
            entry_idx, new_entry = confirmed
            # เลื่อน SL/TP รักษาระยะ R เดิม (ยืนยันทิศแล้ว ไม่ทำ RR แย่ลง)
            shift = new_entry - signal.entry
            signal.entry = new_entry
            signal.sl = signal.sl + shift
            signal.tp = signal.tp + shift

        # โต๊ะความเสี่ยงกลาง (firm-wide pre-trade desk) — ทุกทีมต้องผ่านก่อนเข้าไม้จริง
        if pre_trade_gate:
            atr_g = float(atr_series.iloc[i]) if not pd.isna(atr_series.iloc[i]) else 0.0
            atr_med_g = (
                float(atr_median_series.iloc[i])
                if not pd.isna(atr_median_series.iloc[i]) else atr_g
            )
            if atr_g > 0:
                ctx_window = df.iloc[max(0, i - 250) : i + 1]
                pt = compute_pre_trade_context(
                    ctx_window, signal.direction, signal.entry, signal.sl, signal.tp,
                    atr_g, atr_med_g,
                )
                if pt.skip_recommended or pt.quality_score < pre_trade_min_quality:
                    if logger is not None:
                        sid = logger.log_signal(
                            bar_time=df.index[i], strategy=strategy.name,
                            direction=signal.direction.value, entry=signal.entry,
                            sl=signal.sl, tp=signal.tp, reason=signal.reason,
                        )
                        logger.log_decision(
                            sid, approved=False,
                            reason=f"pre-trade skip: score {pt.quality_score:.0f} | "
                                   + "; ".join(pt.skip_reasons[:2]),
                        )
                    i += 1
                    continue

        signal_id = None
        if logger is not None:
            discussion = signal.meta.get("discussion")
            signal_id = logger.log_signal(
                bar_time=df.index[i],
                strategy=strategy.name,
                direction=signal.direction.value,
                entry=signal.entry,
                sl=signal.sl,
                tp=signal.tp,
                reason=signal.reason,
                discussion=json.dumps(discussion, ensure_ascii=False) if discussion else None,
            )

        atr_now = float(atr_series.iloc[i]) if not pd.isna(atr_series.iloc[i]) else 0.0
        atr_med = (
            float(atr_median_series.iloc[i]) if not pd.isna(atr_median_series.iloc[i]) else atr_now
        )
        current_dd_pct = (
            (state.peak_balance - state.balance) / state.peak_balance * 100.0
            if state.peak_balance > 0 else 0.0
        )
        risk_scale = (
            risk.volatility_scale(atr_now, atr_med)
            * risk.drawdown_budget_scale(current_dd_pct)
            * gate.risk_scale
        )
        plan = risk.size_position(signal.entry, signal.sl, state.balance, risk_scale=risk_scale)
        if not plan.approved:
            if logger is not None and signal_id is not None:
                logger.log_decision(signal_id, approved=False, reason=plan.reason)
            i += 1
            continue

        if logger is not None and signal_id is not None:
            logger.log_decision(signal_id, approved=True, reason=plan.reason, lot=plan.lot)

        exit_idx, parts, outcome, mae_r, mfe_r = _simulate_trade(
            df, entry_idx + 1, signal.direction, signal.entry, signal.sl, signal.tp, max_hold, management
        )

        # ต้นทุนปรับตาม session (ชั่วโมง UTC ของแท่งที่เข้าไม้) + volatility regime ณ ตอนนั้น —
        # แทนที่ round_trip_cost คงที่ตัวเดียวตลอด backtest (เดิมไม่เคยรู้จักคำว่า "spread กระโดด")
        round_trip_cost = cost.round_trip_cost_at(bar_time.hour, atr_now, atr_med)
        risk_dist = abs(signal.entry - signal.sl)
        pnl = sum(
            (signal.direction.sign * (exit_price - signal.entry) - round_trip_cost)
            * fraction * plan.lot * risk_cfg.contract_size
            for fraction, exit_price in parts
        )
        avg_exit = sum(f * p for f, p in parts) / sum(f for f, p in parts)
        actual_risk_amount = risk_dist * plan.lot * risk_cfg.contract_size
        pnl_r = pnl / actual_risk_amount if actual_risk_amount > 0 else 0.0

        post_exit_r = None
        if outcome in ("tp", "tp_after_partial"):
            post_exit_r = _post_exit_run(df, exit_idx, signal.direction, signal.tp, risk_dist)

        on_trade_closed(state, pnl, exit_idx, management.cooldown_bars_after_loss)

        trade = Trade(
            direction=signal.direction,
            entry_time=df.index[entry_idx],
            entry=signal.entry,
            sl=signal.sl,
            tp=signal.tp,
            lot=plan.lot,
            exit_time=df.index[exit_idx],
            exit_price=avg_exit,
            pnl=pnl,
            outcome=outcome,
            regime=regime_series.iloc[i],
            pnl_r=round(pnl_r, 3),
            mae_r=round(mae_r, 3),
            mfe_r=round(mfe_r, 3),
            post_exit_r=round(post_exit_r, 3) if post_exit_r is not None else None,
        )
        discussion = signal.meta.get("discussion") or []
        dissents = sum(1 for o in discussion if not o.get("approve", True))
        total_score, score_detail = score_trade(
            outcome, trade.pnl_r, trade.mae_r, trade.mfe_r, dissents
        )
        trade.review = (
            review_trade(outcome, trade.pnl_r, trade.mae_r, trade.mfe_r, trade.post_exit_r)
            + f" | คะแนนไม้ {total_score}/60 ({score_detail})"
        )
        trades.append(trade)
        balance_points.append((df.index[exit_idx], state.balance))

        if logger is not None and signal_id is not None:
            logger.log_trade(signal_id, trade)

        i = exit_idx + 1

    equity_curve = pd.Series(
        {t: b for t, b in balance_points}
    ).reindex(df.index).ffill().bfill()

    return BacktestResult(
        strategy_name=strategy.name,
        trades=trades,
        equity_curve=equity_curve,
        halted_at=halted_at,
        halt_reason=halt_reason,
    )

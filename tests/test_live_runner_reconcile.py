"""ทดสอบ 2 บั๊กที่เจอจาก audit รอบสอง:
1. dry_run เดิม reconcile_open_position() return เฉยๆ ไม่เคยอัปเดตราคา/ปิดไม้เลย ทำให้ทั้ง
   dashboard ราคาไม่ขยับ และ process_bar เข้าไม้ใหม่ทับไม้เดิมทุกแท่ง (เพราะเช็ค open_ticket ที่
   เป็น None เสมอในโหมด dry-run แทนที่จะเช็ค open_trade_id)
2. magic number mismatch ต้องถูกปฏิเสธใน broker (กัน ticket reuse ไปเผลอแก้ position ทีมอื่น)
"""
import pandas as pd
import pytest

from backtest.costs import CostModel
from core.signal import Direction
from execution.broker import MT5Broker, compute_magic
from execution.live_runner import GateState, LiveTeam, ManageState, reconcile_open_position
from persistence.db import RunLogger
from risk.position_sizing import RiskConfig, RiskManager


def _make_df(closes):
    idx = pd.date_range("2026-07-13", periods=len(closes), freq="30min")
    return pd.DataFrame(
        {"open": closes, "high": [c + 1 for c in closes], "low": [c - 1 for c in closes],
         "close": closes, "volume": [100] * len(closes)},
        index=idx,
    )


def _make_lt(db_path, closes, entry, sl, tp, lot=0.1, direction=Direction.BUY):
    df = _make_df(closes)
    logger = RunLogger(db_path, run_id="live_test_team_M30_x")
    logger.start_run("test_team", initial_balance=10000.0, timeframe="M30")
    signal_id = logger.log_signal(
        bar_time=df.index[0], strategy="test_team", direction=direction.value,
        entry=entry, sl=sl, tp=tp, reason="test",
    )
    trade_id = logger.log_trade_open(
        signal_id=signal_id, direction=direction.value, entry_time=df.index[0],
        entry=entry, sl=sl, tp=tp, lot=lot, ticket=None,
    )
    lt = LiveTeam(
        team="test_team", timeframe="M30", strategy=None, cfg={"trade_management": {}}, df=df,
        last_bar_time=df.index[-1], state=GateState(balance=10000.0),
        risk=RiskManager(RiskConfig(account_balance=10000.0)), risk_cfg=RiskConfig(account_balance=10000.0),
        logger=logger, management=None,
    )
    lt.open_trade_id = trade_id
    lt.open_entry_meta = {"entry": entry, "sl": sl, "tp": tp, "lot": lot, "direction": direction}
    return lt, logger


def test_dry_run_reconcile_updates_price_every_poll(tmp_path):
    """ก่อนแก้: dry_run reconcile แค่ return เฉยๆ ราคาไม่เคยอัปเดต — ตอนนี้ต้องอัปเดตจากแท่งล่าสุด"""
    db_path = str(tmp_path / "live.db")
    lt, logger = _make_lt(db_path, closes=[4058.72], entry=4058.72, sl=4036.98, tp=4102.21)
    cost = CostModel(point_value=100.0)

    reconcile_open_position(broker=None, lt=lt, dry_run=True, cost=cost)
    logger.close()

    from persistence.db import get_trades
    trades = get_trades(db_path, "live_test_team_M30_x")
    row = trades.iloc[0]
    assert row["current_price"] == 4058.72
    assert row["exit_time"] is None or pd.isna(row["exit_time"])


def test_dry_run_reconcile_simulates_tp_close(tmp_path):
    """แท่งล่าสุดแตะ TP แล้ว — dry_run ต้อง "ปิดไม้จำลอง" เอง ไม่งั้นไม้ค้างเปิดตลอดไปและ
    process_bar จะเปิดไม้ใหม่ทับไม้เดิมทุกแท่ง (บั๊กเดิม)
    """
    db_path = str(tmp_path / "live.db")
    entry, sl, tp = 4058.72, 4036.98, 4102.21
    lt, logger = _make_lt(db_path, closes=[tp + 5], entry=entry, sl=sl, tp=tp)  # high จะ >= tp แน่นอน
    cost = CostModel(point_value=100.0)

    reconcile_open_position(broker=None, lt=lt, dry_run=True, cost=cost)
    logger.close()

    assert lt.open_trade_id is None  # ต้องถูกเคลียร์ให้ process_bar เปิดไม้ใหม่ได้

    from persistence.db import get_trades
    trades = get_trades(db_path, "live_test_team_M30_x")
    row = trades.iloc[0]
    assert row["outcome"] == "tp"
    assert not pd.isna(row["exit_time"])
    assert row["pnl"] > 0


def test_get_position_rejects_magic_mismatch(monkeypatch):
    """ticket reuse (สมมติฐาน): position มี magic ไม่ตรงกับที่ทีมคาดไว้ ต้องถือว่า "ไม่ใช่ของเรา" คืน None"""
    broker = MT5Broker(dry_run=False)
    broker._connected = True

    class _FakePos:
        magic = 999999  # ไม่ตรงกับ expected

    import types
    fake_mt5 = types.SimpleNamespace()
    fake_mt5.ACCOUNT_TRADE_MODE_DEMO = 0
    fake_mt5.account_info = lambda: types.SimpleNamespace(trade_mode=0, login=1)
    fake_mt5.positions_get = lambda ticket=None, symbol=None: [_FakePos()]
    broker._mt5 = fake_mt5

    expected = compute_magic("rsi_divergence", "M30")
    assert broker.get_position(12345, expected_magic=expected) is None


def test_get_position_accepts_matching_magic():
    broker = MT5Broker(dry_run=False)
    broker._connected = True
    expected = compute_magic("rsi_divergence", "M30")

    class _FakePos:
        magic = expected

    import types
    fake_mt5 = types.SimpleNamespace()
    fake_mt5.ACCOUNT_TRADE_MODE_DEMO = 0
    fake_mt5.account_info = lambda: types.SimpleNamespace(trade_mode=0, login=1)
    fake_mt5.positions_get = lambda ticket=None, symbol=None: [_FakePos()]
    broker._mt5 = fake_mt5

    assert broker.get_position(12345, expected_magic=expected) is not None

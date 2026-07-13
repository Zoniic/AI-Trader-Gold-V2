"""ทดสอบ bootstrap_team() reattach ไม้ที่เปิดค้างไว้ตอน process restart — โฟกัสที่บั๊ก
partial-fill: ถ้าไม้เคย partial TP ไปแล้วก่อน restart ต้อง "จำ" ว่า partial_done=True และ
lot ที่เหลือถูกต้อง ไม่งั้น manage_open_position() จะพยายามปิดบางส่วนซ้ำด้วย lot เต็ม (ผิด)
"""
import types

from execution.live_runner import bootstrap_team
from execution.broker import MT5Broker
from persistence.db import RunLogger


class _FakePosition:
    def __init__(self, ticket, volume, sl):
        self.ticket = ticket
        self.volume = volume
        self.sl = sl
        self.price_current = 4075.64
        self.profit = 33.08


def _make_fake_mt5(rates_count=100):
    import numpy as np
    import pandas as pd

    fake = types.SimpleNamespace()
    fake.TIMEFRAME_M30 = 30
    idx = pd.date_range("2026-07-01", periods=rates_count, freq="30min")
    rates = np.zeros(rates_count, dtype=[
        ("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"),
        ("close", "f8"), ("tick_volume", "i8"),
    ])
    rates["time"] = (idx.view("i8") // 10**9)
    rates["open"] = rates["high"] = rates["low"] = rates["close"] = 4050.0
    rates["tick_volume"] = 100
    fake.copy_rates_from_pos = lambda symbol, tf, start, count: rates[-count:]
    fake.ACCOUNT_TRADE_MODE_DEMO = 0
    fake.account_info = lambda: types.SimpleNamespace(trade_mode=0, login=1, balance=10000.0)
    return fake


def _seed_open_trade(db_path, team, tf, ticket, lot):
    logger = RunLogger(db_path, run_id=f"live_{team}_{tf}_prev")
    logger.start_run(team, initial_balance=10000.0, timeframe=tf)
    signal_id = logger.log_signal(
        bar_time="2026-07-13 10:00:00", strategy=team, direction="BUY",
        entry=4058.72, sl=4036.98, tp=4102.21, reason="test",
    )
    trade_id = logger.log_trade_open(
        signal_id=signal_id, direction="BUY", entry_time="2026-07-13 10:00:00",
        entry=4058.72, sl=4036.98, tp=4102.21, lot=lot, ticket=ticket,
    )
    logger.close()
    return trade_id


def test_bootstrap_reattach_marks_partial_done_when_broker_lot_is_smaller(tmp_path, monkeypatch):
    """ไม้เปิดไว้ 0.10 lot แล้ว partial TP ปิดไปครึ่งนึงก่อน restart (broker เหลือ 0.05 lot จริง)
    — bootstrap_team ต้องตรวจพบว่า lot ไม่ตรงกับตอนเปิด แล้วตั้ง partial_done=True + remaining_lot
    ให้ตรงกับของจริงใน broker ไม่ใช่ค่า default (False / lot เต็ม) ที่จะทำให้ปิดซ้ำผิดพลาด
    """
    db_path = str(tmp_path / "live.db")
    _seed_open_trade(db_path, "rsi_divergence", "M30", ticket=381893790, lot=0.10)

    broker = MT5Broker(dry_run=False)
    broker._connected = True
    broker._mt5 = _make_fake_mt5()
    broker._mt5.ACCOUNT_TRADE_MODE_DEMO = 0
    broker._mt5.account_info = lambda: types.SimpleNamespace(trade_mode=0, login=1, balance=10000.0)
    broker._mt5.positions_get = lambda ticket=None, symbol=None: (
        [_FakePosition(ticket=381893790, volume=0.05, sl=4058.72)] if ticket == 381893790 else []
    )

    lt = bootstrap_team(
        broker, "rsi_divergence", "M30", "GOLD", account_balance=10000.0, db_path=db_path, dry_run=False,
    )

    assert lt.open_ticket == 381893790
    assert lt.manage_state is not None
    assert lt.manage_state.partial_done is True
    assert lt.manage_state.remaining_lot == 0.05


def test_bootstrap_reattach_leaves_partial_done_false_when_lot_unchanged(tmp_path):
    """ถ้ายังไม่เคย partial TP (broker lot == lot ตอนเปิดเป๊ะ) ต้องไม่ mark partial_done=True เท็จๆ"""
    db_path = str(tmp_path / "live.db")
    _seed_open_trade(db_path, "rsi_divergence", "M30", ticket=555, lot=0.10)

    broker = MT5Broker(dry_run=False)
    broker._connected = True
    broker._mt5 = _make_fake_mt5()
    broker._mt5.ACCOUNT_TRADE_MODE_DEMO = 0
    broker._mt5.account_info = lambda: types.SimpleNamespace(trade_mode=0, login=1, balance=10000.0)
    broker._mt5.positions_get = lambda ticket=None, symbol=None: (
        [_FakePosition(ticket=555, volume=0.10, sl=4036.98)] if ticket == 555 else []
    )

    lt = bootstrap_team(
        broker, "rsi_divergence", "M30", "GOLD", account_balance=10000.0, db_path=db_path, dry_run=False,
    )

    assert lt.manage_state.partial_done is False
    assert lt.manage_state.remaining_lot == 0.10


def test_bootstrap_dry_run_never_touches_broker_positions(tmp_path):
    """dry_run ไม่มี ticket จริงใน MT5 ให้ค้น — ต้องข้าม reattach ไปเงียบๆ ไม่ throw"""
    db_path = str(tmp_path / "live.db")
    broker = MT5Broker(dry_run=True)
    broker._connected = True
    broker._mt5 = _make_fake_mt5()

    lt = bootstrap_team(
        broker, "rsi_divergence", "M30", "GOLD", account_balance=10000.0, db_path=db_path, dry_run=True,
    )
    assert lt.open_ticket is None
    assert lt.manage_state is None

"""ทดสอบด่านความปลอดภัยของ execution/broker.py — จุดนี้พลาดไม่ได้เด็ดขาด"""
import sys
import types

import pytest

from core.signal import Direction
from execution.broker import MT5Broker, NotDemoAccountError


class _FakeAccountInfo:
    def __init__(self, trade_mode, login=12345):
        self.trade_mode = trade_mode
        self.login = login


def _make_fake_mt5(trade_mode: int):
    fake = types.SimpleNamespace()
    fake.ACCOUNT_TRADE_MODE_DEMO = 0
    fake.ACCOUNT_TRADE_MODE_REAL = 2
    fake.initialize = lambda **kwargs: True
    fake.account_info = lambda: _FakeAccountInfo(trade_mode=trade_mode)
    fake.shutdown = lambda: None
    fake.last_error = lambda: "no error"
    fake.ORDER_TYPE_BUY = 0
    fake.ORDER_TYPE_SELL = 1
    fake.TRADE_ACTION_DEAL = 1
    fake.TRADE_RETCODE_DONE = 10009
    fake.ORDER_FILLING_IOC = 1
    fake.symbol_info_tick = lambda symbol: types.SimpleNamespace(ask=1950.0, bid=1949.5)
    return fake


def test_connect_refuses_real_account(monkeypatch):
    fake_mt5 = _make_fake_mt5(trade_mode=2)  # real account, ไม่ใช่ demo
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)

    broker = MT5Broker(dry_run=True)
    with pytest.raises(NotDemoAccountError):
        broker.connect(login=1, password="x", server="x")
    assert broker._connected is False


def test_connect_accepts_demo_account(monkeypatch):
    fake_mt5 = _make_fake_mt5(trade_mode=0)  # demo
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)

    broker = MT5Broker(dry_run=True)
    assert broker.connect(login=1, password="x", server="x") is True
    assert broker._connected is True


def test_dry_run_send_order_never_calls_real_order_send(monkeypatch):
    calls = {"order_send": 0}
    fake_mt5 = _make_fake_mt5(trade_mode=0)

    def _order_send(request):
        calls["order_send"] += 1
        return types.SimpleNamespace(retcode=fake_mt5.TRADE_RETCODE_DONE, order=999)

    fake_mt5.order_send = _order_send
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)

    broker = MT5Broker(dry_run=True)
    broker.connect(login=1, password="x", server="x")
    result = broker.send_order("XAUUSD", Direction.BUY, lot=0.1, sl=1900.0, tp=1950.0)

    assert result.success is True
    assert result.message == "dry_run"
    assert calls["order_send"] == 0  # dry_run ต้องไม่ยิงจริงเด็ดขาด


def test_send_order_refuses_if_account_flips_to_real_after_connect(monkeypatch):
    """เผื่อกรณีสลับบัญชีระหว่างรัน (ไม่ได้ปิดโปรแกรมแล้วเปิดใหม่) — ต้องเช็คซ้ำทุกครั้งก่อนยิง"""
    fake_mt5 = _make_fake_mt5(trade_mode=0)
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)

    broker = MT5Broker(dry_run=False)
    broker.connect(login=1, password="x", server="x")

    fake_mt5.account_info = lambda: _FakeAccountInfo(trade_mode=2)  # สลับเป็นบัญชีจริงกลางคัน

    with pytest.raises(NotDemoAccountError):
        broker.send_order("XAUUSD", Direction.BUY, lot=0.1, sl=1900.0, tp=1950.0)

"""เทสต์ _confirm_entry — ไม้กระดาษยืนยันทิศก่อนเข้าจริง (causal, ไม่ lookahead)"""
import pandas as pd

from backtest.engine import _confirm_entry
from core.signal import Direction


def _df(rows):
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="h")
    return pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close"]).assign(volume=100)


def test_confirm_when_price_moves_in_favor():
    # BUY entry=100, SL=98 (R=2), threshold 0.5R -> target 101. แท่งถัดไปปิด 101.5 = ยืนยัน
    df = _df([[100, 100.2, 99.8, 100], [100, 101.6, 99.9, 101.5]])
    res = _confirm_entry(df, 0, Direction.BUY, entry=100, sl=98, confirm_bars=3, threshold_r=0.5)
    assert res is not None
    entry_idx, entry_price = res
    assert entry_idx == 1
    assert entry_price == 101.5


def test_reject_when_hits_sl_first():
    # ราคาดิ่งชน SL(98) ก่อนถึง target = สัญญาณหลอก ยกเลิก
    df = _df([[100, 100.2, 99.8, 100], [100, 100.1, 97.5, 97.8]])
    res = _confirm_entry(df, 0, Direction.BUY, entry=100, sl=98, confirm_bars=3, threshold_r=0.5)
    assert res is None


def test_reject_when_no_confirmation_within_window():
    # ราคานิ่งไม่ถึง target ภายใน K แท่ง = โมเมนตัมไม่มา ยกเลิก
    df = _df([[100, 100.2, 99.8, 100]] + [[100, 100.3, 99.9, 100.1]] * 3)
    res = _confirm_entry(df, 0, Direction.BUY, entry=100, sl=98, confirm_bars=3, threshold_r=0.5)
    assert res is None


def test_sell_confirmation():
    # SELL entry=100, SL=102 (R=2), threshold 0.5R -> target 99. แท่งถัดไปปิด 98.5 = ยืนยัน
    df = _df([[100, 100.2, 99.8, 100], [100, 100.1, 98.4, 98.5]])
    res = _confirm_entry(df, 0, Direction.SELL, entry=100, sl=102, confirm_bars=3, threshold_r=0.5)
    assert res is not None
    assert res[0] == 1

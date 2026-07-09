"""เทสต์ trailing stop / snowball ด้วยเส้นทางราคา deterministic

BUY: entry=100, SL=98 (risk 2), TP=106, trailing_stop_r=1.0 (ลาก 2 หลัง extreme),
activate ที่ +1R (102)
"""
import pandas as pd

from backtest.engine import TradeManagement, _simulate_trade
from core.signal import Direction


def _df(bars):
    idx = pd.date_range("2024-01-01", periods=len(bars), freq="h")
    return pd.DataFrame(
        [{"open": o, "high": h, "low": low, "close": c, "volume": 100} for o, h, low, c in bars],
        index=idx,
    )


def test_trailing_ratchets_and_exits_in_profit():
    df = _df([
        (100, 104.0, 99.6, 103.5),  # extreme 104 → activate + SL ลากไป 102 (มีผลแท่งถัดไป)
        (103.5, 103.8, 101.9, 102.5),  # low 101.9 ชน SL 102 → ออกกำไร
    ])
    mgmt = TradeManagement(trailing_stop_r=1.0, trailing_activate_r=1.0)
    exit_idx, parts, outcome, _, mfe_r = _simulate_trade(
        df, 0, Direction.BUY, 100.0, 98.0, 106.0, 50, mgmt
    )
    assert outcome == "trailing_stop"
    assert exit_idx == 1
    assert parts == [(1.0, 102.0)]
    assert mfe_r == 2.0  # extreme 104 = +4 / risk 2


def test_trailing_not_active_before_activation_tp_still_works():
    df = _df([
        (100, 101.5, 99.6, 101.0),   # ยังไม่ถึง activate (102)
        (101, 106.5, 100.8, 106.0),  # ชน TP ปกติ
    ])
    mgmt = TradeManagement(trailing_stop_r=1.0, trailing_activate_r=1.0)
    _, parts, outcome, _, _ = _simulate_trade(
        df, 0, Direction.BUY, 100.0, 98.0, 106.0, 50, mgmt
    )
    assert outcome == "tp"
    assert parts == [(1.0, 106.0)]


def test_snowball_removes_tp_and_lets_winner_run():
    """remove_tp_when_trailing: ราคาทะลุ TP เดิม (106) แต่ไม่ปิด — วิ่งต่อจนโดนลากที่สูงกว่า TP"""
    df = _df([
        (100, 104.0, 99.8, 103.5),   # activate + trail SL → 102
        (103.5, 107.0, 103.0, 106.5),  # ทะลุ 106 แต่ TP ถูกตัดทิ้ง — trail SL → 105
        (106.5, 110.0, 105.5, 109.5),  # trail SL → 108
        (109.5, 109.8, 107.9, 108.2),  # low 107.9 ชน SL 108 → ออกที่ 108 (+4R)
    ])
    mgmt = TradeManagement(
        trailing_stop_r=1.0, trailing_activate_r=1.0, remove_tp_when_trailing=True
    )
    exit_idx, parts, outcome, _, _ = _simulate_trade(
        df, 0, Direction.BUY, 100.0, 98.0, 106.0, 50, mgmt
    )
    assert outcome == "trailing_stop"
    assert exit_idx == 3
    assert parts == [(1.0, 108.0)]  # ออกเหนือ TP เดิม — snowball ทำงานจริง


def test_trailing_sell_side_mirrored():
    df = _df([
        (100, 100.4, 96.0, 96.5),   # SELL: extreme 96 → trail SL ลงมา 98 (risk 2, trail 2)
        (96.5, 98.1, 96.2, 98.0),   # high 98.1 ชน SL 98 → ออกกำไร +1R
    ])
    mgmt = TradeManagement(trailing_stop_r=1.0, trailing_activate_r=1.0)
    _, parts, outcome, _, _ = _simulate_trade(
        df, 0, Direction.SELL, 100.0, 102.0, 94.0, 50, mgmt
    )
    assert outcome == "trailing_stop"
    assert parts == [(1.0, 98.0)]

from risk.position_sizing import RiskConfig, RiskManager


def test_size_position_scales_with_sl_distance():
    rm = RiskManager(RiskConfig(account_balance=10000, risk_per_trade_pct=1.0, contract_size=100))

    tight_sl = rm.size_position(entry=1950.0, sl=1949.0, balance=10000)  # sl distance 1
    wide_sl = rm.size_position(entry=1950.0, sl=1940.0, balance=10000)  # sl distance 10

    assert tight_sl.approved and wide_sl.approved
    assert tight_sl.lot > wide_sl.lot  # ยิ่ง sl ไกล ยิ่งต้องล็อตเล็กลงเพื่อความเสี่ยงเท่ากัน


def test_size_position_rejects_zero_sl_distance():
    rm = RiskManager(RiskConfig())
    plan = rm.size_position(entry=1950.0, sl=1950.0, balance=10000)
    assert plan.approved is False


def test_check_drawdown_kill_switch():
    rm = RiskManager(RiskConfig(max_drawdown_pct=10.0))
    ok, _ = rm.check_drawdown(balance=9500, peak_balance=10000)  # -5%
    assert ok is True
    ok, _ = rm.check_drawdown(balance=8900, peak_balance=10000)  # -11%
    assert ok is False

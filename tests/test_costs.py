from backtest.costs import CostModel


def test_flat_round_trip_cost_unchanged_for_backward_compat():
    """round_trip_cost() เดิมต้องยังทำงานเหมือนเดิมเป๊ะ (ไม่ regress โค้ดเก่าที่ยังเรียกอยู่)"""
    cost = CostModel(spread_points=30.0, slippage_points=5.0, point_value=0.01)
    assert cost.round_trip_cost() == (30.0 + 2 * 5.0) * 0.01


def test_round_trip_cost_at_london_baseline_equals_flat_when_normal_volatility():
    """ชั่วโมง London/NY overlap (baseline, mult=1.0) + volatility ปกติ (ratio=1.0) ต้องเท่ากับ flat cost"""
    cost = CostModel(spread_points=30.0, slippage_points=5.0, point_value=0.01)
    baseline = cost.round_trip_cost_at(hour_utc=10, atr_now=1.0, atr_median=1.0)
    assert baseline == cost.round_trip_cost()


def test_round_trip_cost_at_asian_session_wider_than_london():
    cost = CostModel()
    asian = cost.round_trip_cost_at(hour_utc=3, atr_now=1.0, atr_median=1.0)
    london = cost.round_trip_cost_at(hour_utc=10, atr_now=1.0, atr_median=1.0)
    assert asian > london


def test_round_trip_cost_at_rollover_widest():
    cost = CostModel()
    rollover = cost.round_trip_cost_at(hour_utc=22, atr_now=1.0, atr_median=1.0)
    london = cost.round_trip_cost_at(hour_utc=10, atr_now=1.0, atr_median=1.0)
    assert rollover > london


def test_round_trip_cost_at_high_volatility_widens_spread():
    """ATR ปัจจุบันสูงกว่า median มาก (proxy ของข่าวแรง) ต้องทำให้ต้นทุนสูงขึ้นชัดเจน"""
    cost = CostModel()
    normal = cost.round_trip_cost_at(hour_utc=10, atr_now=1.0, atr_median=1.0)
    volatile = cost.round_trip_cost_at(hour_utc=10, atr_now=2.5, atr_median=1.0)
    assert volatile > normal * 2  # ผันผวน 2.5 เท่า median ต้องต้นทุนกระโดดชัดเจน ไม่ใช่ขยับนิดหน่อย


def test_round_trip_cost_at_is_capped_not_unbounded():
    """ต้นทุนต้องไม่พองไม่มีเพดานแม้ session แย่สุด + volatility สูงสุดพร้อมกัน"""
    cost = CostModel(spread_points=30.0, slippage_points=5.0, point_value=0.01)
    worst_case = cost.round_trip_cost_at(hour_utc=22, atr_now=10.0, atr_median=1.0)
    # เพดาน spread_mult=4.0 -> spread ส่วนสูงสุด = 30*4*0.01 = 1.2 บวก slippage ส่วนขยาย
    assert worst_case < (30.0 * 4.0 + 2 * 5.0 * 3.0) * 0.01 + 1e-9


def test_round_trip_cost_at_zero_median_does_not_crash():
    """atr_median=0 (ช่วงต้นข้อมูลก่อนมี rolling window เต็ม) ต้องไม่ throw"""
    cost = CostModel()
    result = cost.round_trip_cost_at(hour_utc=10, atr_now=1.0, atr_median=0.0)
    assert result > 0

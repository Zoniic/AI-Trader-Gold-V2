"""เทสต์ risk hierarchy ใหม่: daily/weekly loss lock, vol-scaled sizing, cooldown, scorecard"""
import pandas as pd
import pytest

from backtest.costs import CostModel
from backtest.engine import TradeManagement, run_backtest
from backtest.review import score_trade
from core.signal import Direction, MarketData, Signal
from core.strategy import Strategy
from risk.position_sizing import RiskConfig, RiskManager


def test_check_daily_loss_locks_at_threshold():
    rm = RiskManager(RiskConfig(max_daily_loss_pct=3.0))
    ok, _ = rm.check_daily_loss(balance=9800, day_start_balance=10000)  # -2%
    assert ok is True
    ok, reason = rm.check_daily_loss(balance=9650, day_start_balance=10000)  # -3.5%
    assert ok is False
    assert "วัน" in reason


def test_check_weekly_loss_locks_at_threshold():
    rm = RiskManager(RiskConfig(max_weekly_loss_pct=6.0))
    ok, _ = rm.check_weekly_loss(balance=9500, week_start_balance=10000)  # -5%
    assert ok is True
    ok, _ = rm.check_weekly_loss(balance=9300, week_start_balance=10000)  # -7%
    assert ok is False


def test_daily_loss_none_means_unlimited():
    rm = RiskManager(RiskConfig(max_daily_loss_pct=None))
    ok, _ = rm.check_daily_loss(balance=1.0, day_start_balance=10000)
    assert ok is True


def test_volatility_scale_reduces_risk_when_atr_spikes():
    rm = RiskManager(RiskConfig(sizing_mode="vol_scaled", vol_scale_min=0.5, vol_scale_max=1.5))
    normal = rm.volatility_scale(atr=1.0, atr_median=1.0)
    spiked = rm.volatility_scale(atr=4.0, atr_median=1.0)  # ATR 4x ปกติ -> ลด risk
    quiet = rm.volatility_scale(atr=0.2, atr_median=1.0)  # ATR ต่ำกว่าปกติมาก -> เพิ่ม risk แต่ถูก cap
    assert normal == 1.0
    assert spiked == 0.5  # ชน floor
    assert quiet == 1.5  # ชน ceiling


def test_fixed_mode_ignores_volatility():
    rm = RiskManager(RiskConfig(sizing_mode="fixed"))
    assert rm.volatility_scale(atr=10.0, atr_median=1.0) == 1.0


def test_dd_budget_scale_disabled_by_default():
    rm = RiskManager(RiskConfig(max_drawdown_pct=20.0))
    assert rm.drawdown_budget_scale(current_drawdown_pct=0.0) == 1.0
    assert rm.drawdown_budget_scale(current_drawdown_pct=15.0) == 1.0


def test_dd_budget_scale_boosts_when_far_from_ceiling():
    rm = RiskManager(
        RiskConfig(
            dd_targeting=True, max_drawdown_pct=20.0,
            dd_budget_headroom=0.3, dd_budget_boost_cap=1.3, dd_budget_floor=0.4,
        )
    )
    at_zero_dd = rm.drawdown_budget_scale(current_drawdown_pct=0.0)
    at_headroom_edge = rm.drawdown_budget_scale(current_drawdown_pct=6.0)  # 30% ของ 20
    assert at_zero_dd == 1.3
    assert at_headroom_edge == pytest.approx(1.0, abs=1e-9)


def test_dd_budget_scale_shrinks_near_ceiling():
    rm = RiskManager(
        RiskConfig(
            dd_targeting=True, max_drawdown_pct=20.0,
            dd_budget_headroom=0.3, dd_budget_boost_cap=1.3, dd_budget_floor=0.4,
        )
    )
    near_ceiling = rm.drawdown_budget_scale(current_drawdown_pct=19.0)  # used=95%
    at_ceiling = rm.drawdown_budget_scale(current_drawdown_pct=20.0)  # used=100%
    assert 0.4 <= near_ceiling < 1.0
    assert at_ceiling == pytest.approx(0.4, abs=1e-9)


def test_dd_budget_scale_monotonically_decreasing_with_drawdown():
    rm = RiskManager(RiskConfig(dd_targeting=True, max_drawdown_pct=20.0))
    scales = [rm.drawdown_budget_scale(dd) for dd in (0, 2, 4, 8, 12, 16, 20)]
    assert scales == sorted(scales, reverse=True)


class _AlwaysBuy(Strategy):
    name = "always_buy_cooldown_test"

    def min_lookback(self) -> int:
        return 5

    def evaluate(self, data: MarketData, idx: int) -> Signal:
        close = float(data.df["close"].iloc[idx])
        # SL ปกติอยู่ใต้ entry สำหรับ BUY — ราคาที่ลดลงเรื่อยๆ ในเทสต์นี้ทำให้แพ้ทุกไม้แน่นอน
        return Signal(direction=Direction.BUY, entry=close, sl=close - 2.0, tp=close + 10.0)


def _make_declining_df(n=400):
    """ราคาลดลงทีละนิดทุกแท่งแบบ deterministic — BUY ไม้ไหนก็โดน SL แน่นอน ใช้ทดสอบ cooldown"""
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    close = 2000.0 - 0.5 * pd.RangeIndex(n).to_numpy()
    return pd.DataFrame(
        {"open": close, "high": close + 0.2, "low": close - 0.2, "close": close, "volume": 100},
        index=idx,
    )


def test_cooldown_skips_bars_after_loss():
    df = _make_declining_df(400)
    data = MarketData(df=df)
    cost = CostModel(spread_points=0, slippage_points=0)

    result_no_cooldown = run_backtest(
        _AlwaysBuy(), data, RiskConfig(max_drawdown_pct=99.0), cost,
        management=TradeManagement(cooldown_bars_after_loss=0),
    )
    result_cooldown = run_backtest(
        _AlwaysBuy(), data, RiskConfig(max_drawdown_pct=99.0), cost,
        management=TradeManagement(cooldown_bars_after_loss=20),
    )
    # cooldown ยาวต้องทำให้จำนวนไม้ลดลง (เว้นช่วงหลังแพ้ทุกครั้ง)
    assert len(result_cooldown.trades) < len(result_no_cooldown.trades)


def test_auto_recover_never_permanently_halts():
    df = _make_declining_df(400)
    data = MarketData(df=df)
    cost = CostModel(spread_points=0, slippage_points=0)

    permanent = run_backtest(
        _AlwaysBuy(), data, RiskConfig(max_drawdown_pct=10.0, dd_halt_mode="permanent"), cost,
        management=TradeManagement(),
    )
    auto = run_backtest(
        _AlwaysBuy(), data,
        RiskConfig(max_drawdown_pct=10.0, dd_halt_mode="auto_recover", dd_probation_scale=0.3), cost,
        management=TradeManagement(),
    )
    # permanent halt หยุดถาวร (มี halted_at) — auto_recover ไม่หยุด เทรดต่อได้เรื่อยๆ
    assert permanent.halted_at is not None
    assert auto.halted_at is None
    assert len(auto.trades) > len(permanent.trades)


def test_score_trade_range_and_monotonic_with_pnl():
    low_score, _ = score_trade("sl", pnl_r=-1.0, mae_r=0.1, mfe_r=0.1, dissents=0)
    high_score, _ = score_trade("tp", pnl_r=2.5, mae_r=0.2, mfe_r=2.5, dissents=0)
    assert 0 <= low_score <= 60
    assert 0 <= high_score <= 60
    assert high_score > low_score


def test_score_trade_penalizes_dissent():
    unanimous, _ = score_trade("tp", pnl_r=1.0, mae_r=0.3, mfe_r=1.0, dissents=0)
    dissented, _ = score_trade("tp", pnl_r=1.0, mae_r=0.3, mfe_r=1.0, dissents=1)
    assert unanimous > dissented

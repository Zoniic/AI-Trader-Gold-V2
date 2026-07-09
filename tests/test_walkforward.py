from backtest.costs import CostModel
from backtest.walkforward import run_walkforward
from core.signal import MarketData
from risk.position_sizing import RiskConfig
from strategies.ema_cross import EMACrossStrategy
from tests.helpers import make_synthetic_df


def test_walkforward_flags_inconclusive_when_too_few_trades():
    df = make_synthetic_df(300, seed=3)  # ข้อมูลน้อยมาก
    data = MarketData(df=df)

    report = run_walkforward(
        strategy_factory=EMACrossStrategy,
        data=data,
        risk_cfg=RiskConfig(),
        cost=CostModel(),
        n_folds=5,
        min_trades_per_fold=30,  # เกณฑ์สูงเทียบกับข้อมูลน้อย ต้อง inconclusive แน่นอน
    )

    assert "ข้อมูลไม่พอสรุป" in report.verdict


def test_walkforward_produces_one_result_per_fold():
    df = make_synthetic_df(3000, seed=5)
    data = MarketData(df=df)

    report = run_walkforward(
        strategy_factory=EMACrossStrategy,
        data=data,
        risk_cfg=RiskConfig(),
        cost=CostModel(),
        n_folds=4,
        min_trades_per_fold=3,
    )

    assert len(report.folds) == 4
    assert report.verdict != ""
    assert all(f.metrics["total_trades"] >= 0 for f in report.folds)

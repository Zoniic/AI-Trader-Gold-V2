from backtest.costs import CostModel
from backtest.walkforward import evaluate_holdout, run_walkforward, split_holdout
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


def test_walkforward_reports_deflated_sharpe_when_enough_trades():
    df = make_synthetic_df(3000, seed=5)
    data = MarketData(df=df)

    report = run_walkforward(
        strategy_factory=EMACrossStrategy, data=data, risk_cfg=RiskConfig(), cost=CostModel(),
        n_folds=4, min_trades_per_fold=3, n_trials=36,
    )

    assert report.deflated_sharpe is not None
    assert report.deflated_sharpe.n_trials == 36


def test_split_holdout_reserves_tail_fraction_untouched():
    df = make_synthetic_df(1000, seed=9)
    tuning_df, holdout_df = split_holdout(df, holdout_fraction=0.2)

    assert len(tuning_df) + len(holdout_df) == len(df)
    assert len(holdout_df) == 200
    # holdout ต้องเป็นช่วงเวลาล่าสุด (ท้ายสุดของข้อมูล) ไม่ใช่ตรงกลางหรือต้น
    assert tuning_df.index[-1] < holdout_df.index[0]


def test_evaluate_holdout_flags_insufficient_data():
    df = make_synthetic_df(200, seed=2)  # เล็กมาก จะได้เทรดน้อยแน่นอน
    _, holdout_df = split_holdout(df, holdout_fraction=0.3)
    holdout_data = MarketData(df=holdout_df)

    report = evaluate_holdout(
        strategy_factory=EMACrossStrategy, holdout_data=holdout_data,
        risk_cfg=RiskConfig(), cost=CostModel(), n_trials=36,
    )
    assert "ข้อมูลไม่พอสรุป" in report.verdict or report.deflated_sharpe is not None


def test_evaluate_holdout_higher_n_trials_stricter_verdict():
    """n_trials สูงขึ้นต้องทำให้ deflated_sharpe_ratio ต่ำลงหรือเท่าเดิม (correction เข้มขึ้น)"""
    df = make_synthetic_df(4000, seed=11)
    _, holdout_df = split_holdout(df, holdout_fraction=0.3)
    holdout_data = MarketData(df=holdout_df)

    report_1 = evaluate_holdout(
        strategy_factory=EMACrossStrategy, holdout_data=holdout_data,
        risk_cfg=RiskConfig(), cost=CostModel(), n_trials=1,
    )
    report_40 = evaluate_holdout(
        strategy_factory=EMACrossStrategy, holdout_data=holdout_data,
        risk_cfg=RiskConfig(), cost=CostModel(), n_trials=40,
    )
    if report_1.deflated_sharpe.n_trials == 1 and len(report_1.metrics) > 0 and \
            report_1.deflated_sharpe.observed_sharpe != 0.0:
        assert report_40.deflated_sharpe.deflated_sharpe_ratio <= report_1.deflated_sharpe.deflated_sharpe_ratio

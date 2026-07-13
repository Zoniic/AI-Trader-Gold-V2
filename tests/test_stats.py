import numpy as np

from backtest.stats import bonferroni_alpha, deflated_sharpe_ratio, sharpe_ratio


def test_bonferroni_alpha_shrinks_with_more_trials():
    assert bonferroni_alpha(1, alpha=0.05) == 0.05
    assert bonferroni_alpha(40, alpha=0.05) == 0.05 / 40
    assert bonferroni_alpha(40) < bonferroni_alpha(4)


def test_sharpe_ratio_zero_for_constant_series():
    assert sharpe_ratio([5.0, 5.0, 5.0]) == 0.0  # std=0 -> undefined, return 0 not NaN/inf


def test_sharpe_ratio_positive_for_upward_biased_pnls():
    rng = np.random.default_rng(42)
    pnls = rng.normal(loc=2.0, scale=1.0, size=200)  # ชนะบ่อยกว่าแพ้ชัดเจน
    assert sharpe_ratio(pnls) > 0


def test_deflated_sharpe_more_trials_means_harder_to_pass():
    """ยิ่ง n_trials เยอะ ยิ่งต้องการ Sharpe จริงสูงขึ้นถึงจะผ่าน — สะท้อน multiple-testing bias"""
    rng = np.random.default_rng(1)
    pnls = rng.normal(loc=1.5, scale=1.0, size=300).tolist()

    result_1_trial = deflated_sharpe_ratio(pnls, n_trials=1)
    result_40_trials = deflated_sharpe_ratio(pnls, n_trials=40)

    assert result_1_trial.observed_sharpe == result_40_trials.observed_sharpe
    assert result_40_trials.expected_max_sharpe_by_chance > result_1_trial.expected_max_sharpe_by_chance
    assert result_40_trials.deflated_sharpe_ratio <= result_1_trial.deflated_sharpe_ratio


def test_deflated_sharpe_random_noise_fails_at_high_trial_count():
    """สุ่ม noise ล้วนๆ (ไม่มี edge จริง) ต้อง "ไม่ผ่าน" DSR เมื่อทดสอบด้วย n_trials สูง —
    นี่คือกรณีที่ multiple-testing correction ควรจับได้ (ป้องกัน false positive จาก data-mining)
    """
    rng = np.random.default_rng(7)
    noise_pnls = rng.normal(loc=0.05, scale=1.0, size=100).tolist()  # แทบไม่มี edge จริง

    result = deflated_sharpe_ratio(noise_pnls, n_trials=40)
    assert result.is_significant is False


def test_deflated_sharpe_insufficient_data_returns_zero():
    result = deflated_sharpe_ratio([1.0, 2.0], n_trials=10)
    assert result.deflated_sharpe_ratio == 0.0
    assert result.is_significant is False

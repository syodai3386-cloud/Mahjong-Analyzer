"""analysis.scoring の偏差値変換のテスト。"""

from __future__ import annotations

import statistics

import pytest

from mahjong_analyzer.analysis.scoring import accuracy_score, to_deviation_values, weighted_overall_score


def test_mean_score_maps_to_50() -> None:
    values = to_deviation_values([1.0, 2.0, 3.0])
    assert values[1] == 50.0  # 平均値(2.0)はちょうど偏差値50


def test_lower_is_better_by_default() -> None:
    # EVロスのような「小さいほど良い」指標では、値が小さいほど偏差値が高くなる
    values = to_deviation_values([1.0, 2.0, 3.0])
    assert values[0] > values[1] > values[2]


def test_higher_is_better_flips_direction() -> None:
    values = to_deviation_values([1.0, 2.0, 3.0], higher_is_better=True)
    assert values[0] < values[1] < values[2]


def test_constant_scores_all_map_to_50() -> None:
    values = to_deviation_values([5.0, 5.0, 5.0])
    assert values == [50.0, 50.0, 50.0]


def test_empty_input_returns_empty() -> None:
    assert to_deviation_values([]) == []


def test_standard_deviation_of_output_is_ten() -> None:
    raw = [1.0, 4.0, 2.0, 8.0, 5.0]
    values = to_deviation_values(raw)
    assert abs(statistics.pstdev(values) - 10.0) < 1e-9


def test_accuracy_score_zero_mistakes_is_100() -> None:
    assert accuracy_score(0.0) == 100.0


def test_accuracy_score_all_mistakes_is_0() -> None:
    assert accuracy_score(1.0) == 0.0


def test_accuracy_score_midpoint() -> None:
    assert accuracy_score(0.25) == 75.0


def test_weighted_overall_score_weights_by_sample_size() -> None:
    # 90点(サンプル100件)と50点(サンプル10件)なら、100件側に強く引っ張られる
    score = weighted_overall_score([(90.0, 100), (50.0, 10)])
    assert score == pytest.approx((90.0 * 100 + 50.0 * 10) / 110, abs=0.05)


def test_weighted_overall_score_skips_zero_weight_axes() -> None:
    score = weighted_overall_score([(80.0, 50), (0.0, 0)])
    assert score == 80.0


def test_weighted_overall_score_none_when_no_data() -> None:
    assert weighted_overall_score([(0.0, 0), (0.0, 0)]) is None

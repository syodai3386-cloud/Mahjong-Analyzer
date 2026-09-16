"""押し引き/鳴き/リーチ/着順戦略の各評価軸(単純な集計ロジック)のテスト。"""

from __future__ import annotations

import pytest

from mahjong_analyzer.analysis.axes.naki import naki_axis
from mahjong_analyzer.analysis.axes.push_fold import push_fold_axis
from mahjong_analyzer.analysis.axes.rank_strategy import rank_strategy_axis
from mahjong_analyzer.analysis.axes.riichi import riichi_axis
from mahjong_analyzer.review.mortal_client import MortalDecision


def _decision(**overrides) -> MortalDecision:
    base = dict(
        kyoku_index=0,
        turn=1,
        actor=0,
        decision_type="dahai",
        actual_choice="1m",
        actual_q=0.1,
        best_choice="1m",
        best_q=0.1,
        shanten=1,
    )
    base.update(overrides)
    return MortalDecision(**base)


def test_push_fold_axis_only_counts_defending_dahai() -> None:
    decisions = [
        _decision(is_defending=True, actual_q=0.1, best_q=0.4),
        _decision(is_defending=False, actual_q=0.1, best_q=0.9),  # 押し引き対象外
        _decision(decision_type="pon", is_defending=True),  # dahaiでないので対象外
    ]
    score = push_fold_axis(decisions)
    assert score.sample_size == 1
    assert score.avg_ev_loss == pytest.approx(0.3)


def test_naki_axis_counts_call_types_only() -> None:
    decisions = [
        _decision(decision_type="pon", actual_q=0.1, best_q=0.2),
        _decision(decision_type="chi", actual_q=0.3, best_q=0.3),
        _decision(decision_type="dahai"),
    ]
    score = naki_axis(decisions)
    assert score.sample_size == 2
    assert score.mistake_rate == 0.5  # ponのみEVロスあり


def test_riichi_axis_counts_reach_only() -> None:
    decisions = [
        _decision(decision_type="reach", actual_q=0.5, best_q=0.5),
        _decision(decision_type="dahai"),
    ]
    score = riichi_axis(decisions)
    assert score.sample_size == 1
    assert score.mistake_rate == 0.0


def test_rank_strategy_axis_groups_by_rank_and_all_last() -> None:
    decisions = [
        _decision(rank_at_decision=1, is_all_last=False, actual_q=0.1, best_q=0.1),
        _decision(rank_at_decision=4, is_all_last=True, actual_q=0.1, best_q=0.6),
    ]
    report = rank_strategy_axis(decisions)
    assert report.overall.sample_size == 2
    assert report.by_rank[1].sample_size == 1
    assert report.by_rank[4].avg_ev_loss == 0.5
    assert report.all_last.sample_size == 1

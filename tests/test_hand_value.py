"""手役・打点構築判断軸(牌効率ミス x Mortal評価の突き合わせ)のテスト。"""

from __future__ import annotations

from mahjong_analyzer.analysis.axes.hand_value import classify_hand_value_decisions
from mahjong_analyzer.analysis.efficiency import DiscardMistake
from mahjong_analyzer.review.mortal_client import MortalDecision


def _mistake(**overrides) -> DiscardMistake:
    base = dict(
        kyoku_index=0,
        turn=1,
        actor=0,
        discarded="E",
        shanten_before=2,
        shanten_after_actual=2,
        ukeire_after_actual=4,
        best_discard="9m",
        shanten_after_best=1,
        ukeire_after_best=8,
    )
    base.update(overrides)
    return DiscardMistake(**base)


def _decision(**overrides) -> MortalDecision:
    base = dict(
        kyoku_index=0,
        turn=1,
        actor=0,
        decision_type="dahai",
        actual_choice="E",
        actual_q=0.4,
        best_choice="E",
        best_q=0.4,
        shanten=2,
    )
    base.update(overrides)
    return MortalDecision(**base)


def test_efficiency_mistake_endorsed_by_mortal_is_value_favoring() -> None:
    # 牌効率的には劣る打牌だが、Mortalの最善手と一致する = 打点重視の妥当な選択
    report = classify_hand_value_decisions([_mistake()], [_decision(actual_choice="E", best_choice="E")])
    assert report.value_favoring == 1
    assert report.pure_mistakes == 0


def test_efficiency_mistake_also_rejected_by_mortal_is_pure_mistake() -> None:
    report = classify_hand_value_decisions(
        [_mistake()], [_decision(actual_choice="E", best_choice="9m")]
    )
    assert report.value_favoring == 0
    assert report.pure_mistakes == 1


def test_unmatched_mistake_without_mortal_data_is_counted_separately() -> None:
    report = classify_hand_value_decisions([_mistake()], [])
    assert report.unmatched == 1
    assert report.value_favoring == 0
    assert report.pure_mistakes == 0


def test_value_favoring_rate() -> None:
    report = classify_hand_value_decisions(
        [_mistake(turn=1), _mistake(turn=2)],
        [
            _decision(turn=1, actual_choice="E", best_choice="E"),
            _decision(turn=2, actual_choice="E", best_choice="9m"),
        ],
    )
    assert report.value_favoring_rate == 0.5

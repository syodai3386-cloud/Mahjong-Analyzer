"""web.view_model(ダッシュボードのカード/ランキング/明細行組み立て)のテスト。"""

from __future__ import annotations

from mahjong_analyzer.analysis.axes.base import AxisScore
from mahjong_analyzer.analysis.axes.condition_insights import ConditionInsights
from mahjong_analyzer.analysis.axes.hand_value import HandValueReport
from mahjong_analyzer.analysis.axes.rank_strategy import RankStrategyReport
from mahjong_analyzer.analysis.efficiency import (
    MISTAKE_CATEGORY_MAJOR_UKEIRE_LOSS,
    MISTAKE_CATEGORY_MINOR_UKEIRE_LOSS,
    MISTAKE_CATEGORY_SHANTEN_LOSS,
    DiscardMistake,
)
from mahjong_analyzer.analysis.report import DefenseQualitySummary, ScoreReport
from mahjong_analyzer.web.view_model import build_axis_cards, build_overall_card, mistake_category_breakdown, mistake_detail_rows

_EMPTY_INSIGHTS = ConditionInsights(
    by_session_position=[], after_last_place=None, after_other=None, by_time_of_day=[]
)


def _empty_axis(name: str) -> AxisScore:
    return AxisScore(name=name, sample_size=0, avg_ev_loss=0.0, mistake_rate=0.0)


def _mistake(**overrides) -> DiscardMistake:
    base = dict(
        kyoku_index=0,
        turn=1,
        actor=0,
        discarded="1m",
        shanten_before=2,
        shanten_after_actual=2,
        ukeire_after_actual=4,
        best_discard="9m",
        shanten_after_best=1,
        ukeire_after_best=10,
    )
    base.update(overrides)
    return DiscardMistake(**base)


def _report(**overrides) -> ScoreReport:
    base = dict(
        games_count=1,
        total_mistakes=0,
        total_dahai=0,
        mistakes_by_paipu={},
        excluded_defending_count=0,
        excluded_dora_justified_count=0,
        has_mortal_data=False,
        push_fold=_empty_axis("押し引き"),
        naki=_empty_axis("鳴き判断"),
        riichi=_empty_axis("リーチ判断"),
        rank_strategy=RankStrategyReport(
            overall=_empty_axis("着順/点数状況判断"), by_rank={}, all_last=_empty_axis("オーラス")
        ),
        hand_value=HandValueReport(efficiency_mistakes=0, value_favoring=0, pure_mistakes=0, unmatched=0),
        defense_quality=DefenseQualitySummary(defending_decisions=0, genbutsu_choices=0, non_genbutsu_avg_ev_loss=0.0),
        condition_timeline=[],
        condition_insights=_EMPTY_INSIGHTS,
    )
    base.update(overrides)
    return ScoreReport(**base)


def test_efficiency_card_uses_total_dahai_as_sample_size() -> None:
    report = _report(total_dahai=100, total_mistakes=20)
    cards = build_axis_cards(report)
    efficiency = next(c for c in cards if c.key == "efficiency")
    assert efficiency.score == 80.0
    assert efficiency.sample_size == 100
    assert efficiency.available is True


def test_axis_card_unavailable_when_no_sample() -> None:
    report = _report()  # push_fold等はsample_size=0
    cards = build_axis_cards(report)
    push_fold = next(c for c in cards if c.key == "push_fold")
    assert push_fold.available is False
    assert push_fold.score is None


def test_overall_card_excludes_unavailable_axes() -> None:
    report = _report(total_dahai=100, total_mistakes=0)  # 牌効率のみデータあり(スコア100)
    cards = build_axis_cards(report)
    overall = build_overall_card(cards)
    assert overall.score == 100.0
    assert overall.available is True


def test_mistake_category_breakdown_groups_by_severity() -> None:
    report = _report(
        mistakes_by_paipu={
            "g1": [
                _mistake(shanten_after_actual=3, shanten_after_best=2),  # シャンテン後退
                _mistake(shanten_after_best=2, ukeire_after_actual=1, ukeire_after_best=10),  # 大きな見落とし(loss=9)
                _mistake(shanten_after_best=2, ukeire_after_actual=5, ukeire_after_best=6),  # わずかな見落とし(loss=1)
            ],
        }
    )
    buckets = {b.label: b for b in mistake_category_breakdown(report)}
    assert buckets[MISTAKE_CATEGORY_SHANTEN_LOSS].count == 1
    assert buckets[MISTAKE_CATEGORY_MAJOR_UKEIRE_LOSS].count == 1
    assert buckets[MISTAKE_CATEGORY_MINOR_UKEIRE_LOSS].count == 1
    assert buckets[MISTAKE_CATEGORY_MAJOR_UKEIRE_LOSS].avg_ukeire_loss == 9.0


def test_mistake_detail_rows_include_category() -> None:
    report = _report(
        mistakes_by_paipu={"g1": [_mistake(shanten_after_actual=3, shanten_after_best=2)]}
    )
    rows = mistake_detail_rows(report, date_by_paipu={"g1": "2026/01/01 10:00"})
    assert rows[0]["category"] == MISTAKE_CATEGORY_SHANTEN_LOSS


def test_mistake_detail_rows_uses_date_label_and_sorts_by_loss() -> None:
    report = _report(
        mistakes_by_paipu={
            "g1": [_mistake(ukeire_after_actual=4, ukeire_after_best=6)],  # loss=2
            "g2": [_mistake(ukeire_after_actual=1, ukeire_after_best=10)],  # loss=9
        }
    )
    rows = mistake_detail_rows(report, date_by_paipu={"g1": "2026/01/01 10:00", "g2": "2026/01/02 12:00"})
    assert rows[0]["ukeire_loss"] == 9
    assert rows[0]["date"] == "2026/01/02 12:00"
    assert rows[1]["ukeire_loss"] == 2

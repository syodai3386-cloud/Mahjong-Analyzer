"""condition_insights(セッション内順序・前局結果・時間帯による裏付け集計)のテスト。"""

from __future__ import annotations

from mahjong_analyzer.analysis.axes.condition import GameCondition
from mahjong_analyzer.analysis.axes.condition_insights import analyze_condition


def _cond(paipu_id: str, start_time: int, session_index: int, games_into_session: int, mistake_rate: float) -> GameCondition:
    return GameCondition(
        paipu_id=paipu_id,
        start_time=start_time,
        session_index=session_index,
        games_into_session=games_into_session,
        mistake_rate=mistake_rate,
    )


def test_by_session_position_groups_correctly() -> None:
    timeline = [
        _cond("g1", 0, 0, 1, 0.1),
        _cond("g2", 0, 0, 2, 0.3),
        _cond("g3", 0, 0, 6, 0.5),  # 5局目以降バケットに入る
    ]
    insights = analyze_condition(timeline, rank_by_paipu={})
    by_pos = {b.label: b for b in insights.by_session_position}
    assert by_pos["1局目"].avg_mistake_rate == 0.1
    assert by_pos["2局目"].avg_mistake_rate == 0.3
    assert by_pos["5局目以降"].avg_mistake_rate == 0.5
    assert by_pos["3局目"].sample_size == 0


def test_after_last_place_vs_after_other() -> None:
    timeline = [
        _cond("g1", 0, 0, 1, 0.1),
        _cond("g2", 100, 0, 2, 0.4),  # g1がラスの直後
        _cond("g3", 200, 0, 3, 0.2),  # g2が1位の直後
    ]
    ranks = {"g1": 4, "g2": 1}
    insights = analyze_condition(timeline, rank_by_paipu=ranks)
    assert insights.after_last_place.avg_mistake_rate == 0.4
    assert insights.after_last_place.sample_size == 1
    assert insights.after_other.avg_mistake_rate == 0.2
    assert insights.after_other.sample_size == 1


def test_after_last_place_none_when_no_data() -> None:
    timeline = [_cond("g1", 0, 0, 1, 0.1)]
    insights = analyze_condition(timeline, rank_by_paipu={})
    assert insights.after_last_place is None
    assert insights.after_other is None


def test_time_of_day_bucketing() -> None:
    import datetime

    morning = int(datetime.datetime(2026, 1, 1, 8, 0).timestamp())
    night = int(datetime.datetime(2026, 1, 1, 23, 0).timestamp())
    timeline = [
        _cond("g1", morning, 0, 1, 0.1),
        _cond("g2", night, 1, 1, 0.5),
    ]
    insights = analyze_condition(timeline, rank_by_paipu={})
    labels = {b.label for b in insights.by_time_of_day}
    assert "朝(5-12時)" in labels
    assert "夜(18-24時)" in labels
    assert "昼(12-18時)" not in labels  # データがない時間帯は含まれない

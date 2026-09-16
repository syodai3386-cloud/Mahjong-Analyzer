"""filters(直近N戦・期間指定による牌譜絞り込み)のテスト。"""

from __future__ import annotations

from datetime import date

from mahjong_analyzer.filters import GameFilter, apply_filter
from mahjong_analyzer.parser.model import GameLog, PlayerInfo

_PLAYERS = [PlayerInfo(0, "Me", account_id=42)]


def _game(paipu_id: str, start_time: int | None) -> GameLog:
    return GameLog(paipu_id=paipu_id, players=_PLAYERS, events=[], start_time=start_time, end_time=start_time)


def _ts(y: int, m: int, d: int) -> int:
    import datetime

    return int(datetime.datetime(y, m, d, 12, 0).timestamp())


def test_no_filter_returns_all_games_unchanged() -> None:
    games = [_game("g1", _ts(2026, 1, 1)), _game("g2", None)]
    assert apply_filter(games, GameFilter()) == games


def test_recent_n_keeps_most_recent_games_only() -> None:
    games = [
        _game("g1", _ts(2026, 1, 1)),
        _game("g2", _ts(2026, 1, 2)),
        _game("g3", _ts(2026, 1, 3)),
    ]
    result = apply_filter(games, GameFilter(recent=2))
    assert [g.paipu_id for g in result] == ["g2", "g3"]


def test_date_range_filters_inclusive() -> None:
    games = [
        _game("g1", _ts(2026, 1, 1)),
        _game("g2", _ts(2026, 1, 5)),
        _game("g3", _ts(2026, 1, 10)),
    ]
    result = apply_filter(
        games, GameFilter(date_from=date(2026, 1, 2), date_to=date(2026, 1, 5))
    )
    assert [g.paipu_id for g in result] == ["g2"]


def test_date_range_boundaries_are_inclusive() -> None:
    games = [_game("g1", _ts(2026, 1, 5))]
    result = apply_filter(games, GameFilter(date_from=date(2026, 1, 5), date_to=date(2026, 1, 5)))
    assert [g.paipu_id for g in result] == ["g1"]


def test_games_without_start_time_are_excluded_when_filter_active() -> None:
    games = [_game("g1", _ts(2026, 1, 1)), _game("g2", None)]
    result = apply_filter(games, GameFilter(recent=10))
    assert [g.paipu_id for g in result] == ["g1"]


def test_combined_recent_and_date_range() -> None:
    games = [
        _game("g1", _ts(2026, 1, 1)),
        _game("g2", _ts(2026, 1, 2)),
        _game("g3", _ts(2026, 1, 3)),
        _game("g4", _ts(2026, 1, 4)),
    ]
    # 1/2以降に絞った上で、直近1戦のみ
    result = apply_filter(games, GameFilter(recent=1, date_from=date(2026, 1, 2)))
    assert [g.paipu_id for g in result] == ["g4"]

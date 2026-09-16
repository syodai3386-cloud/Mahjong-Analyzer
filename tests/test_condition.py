"""メンタル/コンディション傾向軸(セッション分割・ミス率の時系列化)のテスト。"""

from __future__ import annotations

from mahjong_analyzer.analysis.axes.condition import compute_condition_timeline
from mahjong_analyzer.analysis.efficiency import DiscardMistake
from mahjong_analyzer.parser.model import GameLog, PlayerInfo

_PLAYERS = [PlayerInfo(0, "Me", account_id=42), PlayerInfo(1, "B"), PlayerInfo(2, "C"), PlayerInfo(3, "D")]

_HAND14 = ["1m", "2m", "3m", "4p", "5p", "6p", "7s", "8s", "9s", "S", "S", "3s", "5s", "E"]


def _game(paipu_id: str, start_time: int, end_time: int, mistake: bool) -> GameLog:
    discard = "S" if mistake else "E"  # "S"は非最適打(牌効率ミス扱い)
    events = [
        {
            "type": "start_kyoku",
            "tehais": [_HAND14, ["?"] * 13, ["?"] * 13, ["?"] * 13],
        },
        {"type": "dahai", "actor": 0, "pai": discard, "tsumogiri": False},
        {"type": "end_kyoku"},
    ]
    return GameLog(paipu_id=paipu_id, players=_PLAYERS, events=events, start_time=start_time, end_time=end_time)


def test_consecutive_games_form_one_session() -> None:
    games = [
        _game("g1", start_time=1000, end_time=1500, mistake=False),
        _game("g2", start_time=1600, end_time=2000, mistake=True),
    ]
    timeline = compute_condition_timeline(games, account_id=42)

    assert timeline[0].session_index == timeline[1].session_index
    assert timeline[0].games_into_session == 1
    assert timeline[1].games_into_session == 2


def test_large_time_gap_starts_new_session() -> None:
    games = [
        _game("g1", start_time=1000, end_time=1500, mistake=False),
        _game("g2", start_time=1500 + 3 * 60 * 60, end_time=1500 + 3 * 60 * 60 + 500, mistake=False),
    ]
    timeline = compute_condition_timeline(games, account_id=42)

    assert timeline[0].session_index != timeline[1].session_index
    assert timeline[1].games_into_session == 1


def test_mistake_rate_reflects_actual_discard() -> None:
    games = [_game("g1", start_time=1000, end_time=1500, mistake=True)]
    timeline = compute_condition_timeline(games, account_id=42)
    assert timeline[0].mistake_rate == 1.0  # 唯一の打牌がミス


def test_games_without_the_target_account_are_skipped() -> None:
    other_players = [PlayerInfo(0, "X", account_id=999)] + _PLAYERS[1:]
    gl = GameLog(paipu_id="g1", players=other_players, events=[], start_time=1000, end_time=1500)
    timeline = compute_condition_timeline([gl], account_id=42)
    assert timeline == []


def test_date_label_formats_start_time_as_readable_datetime() -> None:
    # paipu_idのハッシュ列は読みづらいので、start_timeから実際の日時を表示する
    games = [_game("g1", start_time=1669113793, end_time=1669115348, mistake=False)]
    timeline = compute_condition_timeline(games, account_id=42)
    assert timeline[0].date_label  # 空でない
    assert "/" in timeline[0].date_label
    assert ":" in timeline[0].date_label


def test_attacking_dahai_denominator_overrides_raw_dahai_count() -> None:
    # このgameの生の打牌数は1だが、防御中を除いた「攻めの打牌数」は0とみなす。
    games = [_game("g1", start_time=1000, end_time=1500, mistake=True)]
    timeline = compute_condition_timeline(
        games, account_id=42, mistakes_by_paipu={"g1": []}, attacking_dahai_by_paipu={"g1": 0}
    )
    assert timeline[0].mistake_rate == 0.0  # 分母0のときは0扱い(ゼロ除算にしない)


def test_precomputed_mistakes_are_used_instead_of_recomputing() -> None:
    # discard="E"(牌効率的には最善)のゲームでも、precomputedで「ミスがあった」
    # ことにすれば、find_mistakes()を再実行せずそちらが優先されることを確認する。
    games = [_game("g1", start_time=1000, end_time=1500, mistake=False)]
    fake_mistake = DiscardMistake(
        kyoku_index=0,
        turn=1,
        actor=0,
        discarded="E",
        shanten_before=1,
        shanten_after_actual=1,
        ukeire_after_actual=1,
        best_discard="E",
        shanten_after_best=1,
        ukeire_after_best=1,
    )
    timeline = compute_condition_timeline(
        games, account_id=42, mistakes_by_paipu={"g1": [fake_mistake]}
    )
    assert timeline[0].mistake_rate == 1.0

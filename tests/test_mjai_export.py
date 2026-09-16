"""review.mjai_export の視点マスキングのテスト(Mortal本体は不要)。"""

from __future__ import annotations

from mahjong_analyzer.parser.model import GameLog, PlayerInfo
from mahjong_analyzer.review.mjai_export import HIDDEN_TILE, to_mjai_events

_PLAYERS = [PlayerInfo(0, "A"), PlayerInfo(1, "B"), PlayerInfo(2, "C"), PlayerInfo(3, "D")]

_HAND0 = ["1m", "2m", "3m", "4p", "5p", "6p", "7s", "8s", "9s", "1s", "1s", "1s", "E"]
_HAND1 = ["2m", "3m", "4m", "5m", "6m", "7m", "1p", "2p", "3p", "4s", "5s", "6s", "9p"]


def _game_log(events: list[dict]) -> GameLog:
    return GameLog(paipu_id="test", players=_PLAYERS, events=events)


def test_start_kyoku_masks_other_players_tehai() -> None:
    events = [
        {
            "type": "start_kyoku",
            "tehais": [_HAND0, _HAND1, ["?"] * 13, ["?"] * 13],
        }
    ]
    mjai = to_mjai_events(_game_log(events), perspective_seat=0)
    start_kyoku = next(ev for ev in mjai if ev["type"] == "start_kyoku")

    assert start_kyoku["tehais"][0] == _HAND0  # 自分の手は見える
    assert start_kyoku["tehais"][1] == [HIDDEN_TILE] * 13  # 他家は伏せる
    assert start_kyoku["tehais"][2] == [HIDDEN_TILE] * 13


def test_tsumo_masks_other_players_drawn_tile() -> None:
    events = [
        {"type": "tsumo", "actor": 0, "pai": "5m"},
        {"type": "tsumo", "actor": 1, "pai": "9p"},
    ]
    mjai = to_mjai_events(_game_log(events), perspective_seat=0)
    tsumo_events = [ev for ev in mjai if ev["type"] == "tsumo"]

    assert tsumo_events[0]["pai"] == "5m"  # 自分のツモは見える
    assert tsumo_events[1]["pai"] == HIDDEN_TILE  # 他家のツモは伏せる


def test_perspective_changes_which_hand_is_visible() -> None:
    events = [
        {
            "type": "start_kyoku",
            "tehais": [_HAND0, _HAND1, ["?"] * 13, ["?"] * 13],
        }
    ]
    mjai = to_mjai_events(_game_log(events), perspective_seat=1)
    start_kyoku = next(ev for ev in mjai if ev["type"] == "start_kyoku")

    assert start_kyoku["tehais"][0] == [HIDDEN_TILE] * 13
    assert start_kyoku["tehais"][1] == _HAND1


def test_public_events_are_never_masked() -> None:
    events = [
        {"type": "dahai", "actor": 2, "pai": "9m", "tsumogiri": False},
        {"type": "pon", "actor": 3, "target": 2, "pai": "9m", "consumed": ["9m", "9m"]},
        {"type": "reach", "actor": 2},
    ]
    mjai = to_mjai_events(_game_log(events), perspective_seat=0)
    dahai, pon, reach = (ev for ev in mjai if ev["type"] in {"dahai", "pon", "reach"})

    assert dahai["pai"] == "9m"
    assert pon["consumed"] == ["9m", "9m"]
    assert reach["actor"] == 2


def test_first_line_is_start_game_with_player_names() -> None:
    mjai = to_mjai_events(_game_log([]), perspective_seat=0)
    assert mjai[0] == {"type": "start_game", "names": ["A", "B", "C", "D"]}

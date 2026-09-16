"""降り技術の質(現物選択の有無)のテスト。"""

from __future__ import annotations

from mahjong_analyzer.analysis.axes.defense_quality import defense_quality_axis
from mahjong_analyzer.parser.model import GameLog, PlayerInfo
from mahjong_analyzer.review.mortal_client import MortalDecision

_PLAYERS = [PlayerInfo(0, "A"), PlayerInfo(1, "B"), PlayerInfo(2, "C"), PlayerInfo(3, "D")]


def _game_log() -> GameLog:
    events = [
        {"type": "start_kyoku", "bakaze": "E", "kyoku": 1, "scores": [25000, 25000, 25000, 25000]},
        {"type": "dahai", "actor": 1, "pai": "5p", "tsumogiri": False},
        {"type": "reach", "actor": 1},
        # actor=1のリーチ後、actor=0は現物(5p)を切る場面と切らない場面を作る
        {"type": "dahai", "actor": 0, "pai": "5p", "tsumogiri": False},
        {"type": "dahai", "actor": 1, "pai": "9m", "tsumogiri": True},
        {"type": "dahai", "actor": 0, "pai": "8m", "tsumogiri": False},
    ]
    return GameLog(paipu_id="test", players=_PLAYERS, events=events)


def test_genbutsu_choice_is_counted_separately_from_ev_loss() -> None:
    decisions = [
        MortalDecision(
            kyoku_index=0,
            turn=1,
            actor=0,
            decision_type="dahai",
            actual_choice="5p",
            actual_q=0.3,
            best_choice="5p",
            best_q=0.3,
            shanten=2,
            is_defending=True,
        ),
        MortalDecision(
            kyoku_index=0,
            turn=2,
            actor=0,
            decision_type="dahai",
            actual_choice="8m",
            actual_q=0.1,
            best_choice="5p",
            best_q=0.5,
            shanten=2,
            is_defending=True,
        ),
    ]
    report = defense_quality_axis(_game_log(), decisions)

    assert report.defending_decisions == 2
    assert report.genbutsu_choices == 1  # 1回目の5pのみ現物
    assert report.non_genbutsu_avg_ev_loss == 0.4  # 2回目(8m)のEVロスのみ集計
    assert report.genbutsu_rate == 0.5

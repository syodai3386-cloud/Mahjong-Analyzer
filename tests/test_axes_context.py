"""analysis.axes.context の文脈計算(押し引き/着順)のテスト。"""

from __future__ import annotations

from mahjong_analyzer.analysis.axes.context import compute_context, count_attacking_dahai, enrich_with_context
from mahjong_analyzer.parser.model import GameLog, PlayerInfo
from mahjong_analyzer.review.mortal_client import MortalDecision

_PLAYERS = [PlayerInfo(0, "A"), PlayerInfo(1, "B"), PlayerInfo(2, "C"), PlayerInfo(3, "D")]


def _game_log(events: list[dict]) -> GameLog:
    return GameLog(paipu_id="test", players=_PLAYERS, events=events)


def test_is_defending_false_before_any_riichi() -> None:
    events = [
        {"type": "start_kyoku", "bakaze": "E", "kyoku": 1, "scores": [25000, 25000, 25000, 25000]},
        {"type": "dahai", "actor": 0, "pai": "1m", "tsumogiri": False},
    ]
    ctx = compute_context(_game_log(events))
    assert ctx[(0, 0, 1)].is_defending is False


def test_is_defending_true_after_opponent_riichi() -> None:
    events = [
        {"type": "start_kyoku", "bakaze": "E", "kyoku": 1, "scores": [25000, 25000, 25000, 25000]},
        {"type": "dahai", "actor": 1, "pai": "5p", "tsumogiri": False},
        {"type": "reach", "actor": 1},
        {"type": "dahai", "actor": 2, "pai": "9m", "tsumogiri": False},
    ]
    ctx = compute_context(_game_log(events))
    # actor=1自身の直後の判断は「自分のリーチ」なので危険地帯には数えない
    assert ctx[(0, 1, 1)].is_defending is False
    # actor=2 は actor=1 のリーチ後の打牌なので危険地帯
    assert ctx[(0, 2, 1)].is_defending is True


def test_rank_at_decision_reflects_current_scores() -> None:
    events = [
        {"type": "start_kyoku", "bakaze": "E", "kyoku": 1, "scores": [20000, 30000, 25000, 25000]},
        {"type": "dahai", "actor": 0, "pai": "1m", "tsumogiri": False},
    ]
    ctx = compute_context(_game_log(events))
    assert ctx[(0, 0, 1)].rank_at_decision == 4  # 20000は最下位


def test_is_all_last_detects_south_4() -> None:
    events = [
        {"type": "start_kyoku", "bakaze": "S", "kyoku": 4, "scores": [25000, 25000, 25000, 25000]},
        {"type": "dahai", "actor": 0, "pai": "1m", "tsumogiri": False},
    ]
    ctx = compute_context(_game_log(events))
    assert ctx[(0, 0, 1)].is_all_last is True


def test_count_attacking_dahai_excludes_defending_turns() -> None:
    events = [
        {"type": "start_kyoku", "bakaze": "E", "kyoku": 1, "scores": [25000, 25000, 25000, 25000]},
        {"type": "dahai", "actor": 0, "pai": "1m", "tsumogiri": False},  # 攻め(まだ誰もリーチしていない)
        {"type": "dahai", "actor": 1, "pai": "5p", "tsumogiri": False},
        {"type": "reach", "actor": 1},
        {"type": "dahai", "actor": 0, "pai": "2m", "tsumogiri": False},  # actor=1のリーチ後 = 防御中
        {"type": "dahai", "actor": 0, "pai": "3m", "tsumogiri": False},  # 引き続き防御中
    ]
    assert count_attacking_dahai(_game_log(events), seat=0) == 1


def test_enrich_with_context_mutates_dahai_decisions_only() -> None:
    events = [
        {"type": "start_kyoku", "bakaze": "S", "kyoku": 4, "scores": [25000, 25000, 25000, 15000]},
        {"type": "dahai", "actor": 3, "pai": "9m", "tsumogiri": False},
    ]
    decisions = [
        MortalDecision(
            kyoku_index=0,
            turn=1,
            actor=3,
            decision_type="dahai",
            actual_choice="9m",
            actual_q=0.1,
            best_choice="9m",
            best_q=0.1,
            shanten=2,
        ),
        MortalDecision(
            kyoku_index=0,
            turn=1,
            actor=3,
            decision_type="pon",
            actual_choice="pon",
            actual_q=0.1,
            best_choice="none",
            best_q=0.2,
            shanten=2,
        ),
    ]
    enriched = enrich_with_context(_game_log(events), decisions)

    assert enriched[0].rank_at_decision == 4
    assert enriched[0].is_all_last is True
    # decision_type != "dahai" は現状スコープ外なのでデフォルトのまま
    assert enriched[1].rank_at_decision is None

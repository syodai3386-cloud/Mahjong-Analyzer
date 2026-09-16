"""review.mortal_client のq_values差分計算ロジックのテスト。

実際のMortalプロセスは起動せず、MortalEngineプロトコルを満たす
フェイク実装(出力フォーマットは公式ドキュメントで確認できた
`meta.q_values`/`shanten`の形に基づく想定値)で検証する。
"""

from __future__ import annotations

from mahjong_analyzer.parser.model import GameLog, PlayerInfo
from mahjong_analyzer.review.mortal_client import build_decisions_for_seat

_PLAYERS = [PlayerInfo(0, "A"), PlayerInfo(1, "B"), PlayerInfo(2, "C"), PlayerInfo(3, "D")]


class _FakeEngine:
    def __init__(self, outputs: list[dict]):
        self._outputs = outputs

    def run(self, mjai_jsonl: str) -> list[dict]:
        return self._outputs


def _game_log() -> GameLog:
    events = [
        {"type": "start_kyoku", "tehais": [["1m"] * 13, ["?"] * 13, ["?"] * 13, ["?"] * 13]},
        {"type": "dahai", "actor": 0, "pai": "1m", "tsumogiri": False},
    ]
    return GameLog(paipu_id="test", players=_PLAYERS, events=events)


def test_build_decisions_picks_out_own_seat_only() -> None:
    outputs = [
        {"type": "start_kyoku"},
        {
            "type": "dahai",
            "actor": 0,
            "pai": "1m",
            "meta": {"q_values": {"1m": 0.2, "9m": 0.5}, "shanten": 2},
        },
        {
            "type": "dahai",
            "actor": 1,
            "pai": "5p",
            "meta": {"q_values": {"5p": 0.1, "6p": 0.3}, "shanten": 3},
        },
    ]
    decisions = build_decisions_for_seat(_game_log(), perspective_seat=0, engine=_FakeEngine(outputs))

    assert len(decisions) == 1
    d = decisions[0]
    assert d.actor == 0
    assert d.actual_choice == "1m"
    assert d.actual_q == 0.2
    assert d.best_choice == "9m"
    assert d.best_q == 0.5
    assert d.ev_loss == 0.3
    assert d.shanten == 2


def test_build_decisions_zero_ev_loss_when_actual_is_best() -> None:
    outputs = [
        {"type": "start_kyoku"},
        {
            "type": "dahai",
            "actor": 0,
            "pai": "9m",
            "meta": {"q_values": {"1m": 0.2, "9m": 0.5}, "shanten": 2},
        },
    ]
    decisions = build_decisions_for_seat(_game_log(), perspective_seat=0, engine=_FakeEngine(outputs))

    assert decisions[0].ev_loss == 0.0


def test_build_decisions_skips_events_without_q_values() -> None:
    outputs = [
        {"type": "start_kyoku"},
        {"type": "dahai", "actor": 0, "pai": "1m", "meta": {}},
    ]
    decisions = build_decisions_for_seat(_game_log(), perspective_seat=0, engine=_FakeEngine(outputs))
    assert decisions == []

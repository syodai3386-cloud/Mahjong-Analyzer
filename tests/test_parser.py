"""majsoul_to_mjai変換のテスト(ネットワーク・アカウント不要)。"""

from __future__ import annotations

import json
from pathlib import Path

from mahjong_analyzer.parser.majsoul_to_mjai import convert
from mahjong_analyzer.parser.model import GameLog

FIXTURE = Path(__file__).parent / "fixtures" / "raw_game_basic.json"


def _load() -> GameLog:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return convert(raw)


def test_players_are_extracted_in_seat_order() -> None:
    gl = _load()
    assert [p.seat for p in gl.players] == [0, 1, 2, 3]
    assert [p.name for p in gl.players] == ["Alice", "Bob", "Carl", "Dan"]


def test_start_kyoku_fields_and_tile_conversion() -> None:
    gl = _load()
    start = next(e for e in gl.events if e["type"] == "start_kyoku")

    assert start["bakaze"] == "E"
    assert start["kyoku"] == 2  # ju(1) + 1
    assert start["honba"] == 1
    assert start["kyotaku"] == 1
    assert start["oya"] == 1  # ju % 4
    assert start["dora_marker"] == "5pr"  # 雀魂の "0p"(赤5p) はmjaiで "5pr"

    # 字牌の変換(1z/3z/5z -> E/W/P)を含む手牌が正しく変換されていること
    assert start["tehais"][2][-2:] == ["E", "W"]
    assert start["tehais"][3][-1] == "P"


def test_tsumo_red_five_conversion() -> None:
    gl = _load()
    tsumo_events = [e for e in gl.events if e["type"] == "tsumo"]
    tiles_drawn = [e["pai"] for e in tsumo_events]
    assert "5sr" in tiles_drawn  # 雀魂の "0s" が赤5sに変換されている


def test_reach_event_emitted_on_riichi_discard() -> None:
    gl = _load()
    reach_events = [e for e in gl.events if e["type"] == "reach"]
    assert len(reach_events) == 1
    assert reach_events[0]["actor"] == 2


def test_ankan_splits_concatenated_tiles_and_emits_new_dora() -> None:
    gl = _load()
    ankan = next(e for e in gl.events if e["type"] == "ankan")
    assert ankan["actor"] == 0
    assert ankan["consumed"] == ["1s", "1s", "1s", "1s"]

    dora_events = [e for e in gl.events if e["type"] == "dora"]
    assert len(dora_events) == 1
    assert dora_events[0]["dora_marker"] == "S"  # "2z" -> "S"


def test_chi_call_separates_consumed_from_called_tile() -> None:
    gl = _load()
    chi = next(e for e in gl.events if e["type"] == "chi")
    assert chi["actor"] == 2
    assert sorted(chi["consumed"]) == ["7p", "8p"]
    assert chi["pai"] == "9p"
    assert chi["target"] == 1


def test_hora_infers_ron_target_from_last_discard() -> None:
    gl = _load()
    hora = next(e for e in gl.events if e["type"] == "hora")
    assert hora["actor"] == 3
    assert hora["target"] == 2  # 直前にseat2が捨てた"3z"を3が和了
    assert hora["pai"] == "W"
    assert hora["deltas"] == [0, 0, -3900, 3900]


def test_kyoku_and_game_boundaries_are_closed() -> None:
    gl = _load()
    assert gl.events[-1]["type"] == "end_game"
    assert gl.events[-1]["scores"] == [24000, 26000, 21100, 28900]
    assert any(e["type"] == "end_kyoku" for e in gl.events)

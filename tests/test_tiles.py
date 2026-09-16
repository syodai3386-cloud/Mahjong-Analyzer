"""tiles(ドラ表示牌→ドラ変換)のテスト。"""

from __future__ import annotations

from mahjong_analyzer.tiles import dora_from_indicator


def test_dora_from_indicator_number_tile() -> None:
    assert dora_from_indicator("4p") == "5p"


def test_dora_from_indicator_number_tile_wraps_at_9() -> None:
    assert dora_from_indicator("9s") == "1s"


def test_dora_from_indicator_red_five_uses_base_tile() -> None:
    assert dora_from_indicator("5mr") == "6m"


def test_dora_from_indicator_wind_cycle() -> None:
    assert dora_from_indicator("E") == "S"
    assert dora_from_indicator("N") == "E"  # 北の次は東に戻る


def test_dora_from_indicator_dragon_cycle() -> None:
    assert dora_from_indicator("P") == "F"
    assert dora_from_indicator("C") == "P"  # 中の次は白に戻る

"""打牌効率(シャンテン数・受け入れ枚数・ミス検出)のテスト(ネットワーク・アカウント不要)。"""

from __future__ import annotations

from mahjong_analyzer.analysis.efficiency import (
    MISTAKE_CATEGORY_MAJOR_UKEIRE_LOSS,
    MISTAKE_CATEGORY_MINOR_UKEIRE_LOSS,
    MISTAKE_CATEGORY_SHANTEN_LOSS,
    DiscardMistake,
    classify_mistake,
    count_dora,
    find_mistakes,
    hand_shanten,
    ukeire_for_hand,
)
from mahjong_analyzer.parser.model import GameLog, PlayerInfo

_PLAYERS = [PlayerInfo(0, "A"), PlayerInfo(1, "B"), PlayerInfo(2, "C"), PlayerInfo(3, "D")]


def _game_log(events: list[dict]) -> GameLog:
    return GameLog(paipu_id="test", players=_PLAYERS, events=events)


def test_hand_shanten_pair_is_agari() -> None:
    # 対子1つだけの2枚 = あがり形(他の4面子は暗黙の副露扱い)
    assert hand_shanten(["1m", "1m"]) == -1


def test_hand_shanten_triplet_plus_isolated_is_tenpai() -> None:
    # 刻子+孤立牌 = テンパイ(対子完成待ち)
    assert hand_shanten(["1m", "1m", "1m", "4p"]) == 0


def test_hand_shanten_complete_regular_hand_is_agari() -> None:
    tiles = ["1m", "2m", "3m", "4p", "5p", "6p", "7s", "8s", "9s", "S", "S", "P", "P", "P"]
    assert hand_shanten(tiles) == -1


def test_ukeire_counts_all_four_copies_when_nothing_visible() -> None:
    # 3面子+対子+塔子(4p-6pのカンチャン、待ちは5p)のテンパイ。待ち牌は1種のみ。
    tenpai_hand = ["1m", "2m", "3m", "4p", "6p", "7s", "8s", "9s", "1s", "1s", "1s", "S", "S"]
    shanten, ukeire = ukeire_for_hand(tenpai_hand)
    assert shanten == 0
    assert ukeire == 4  # 5p が場に一切見えていないので4枚とも受け入れ


def test_ukeire_subtracts_visible_tiles() -> None:
    tenpai_hand = ["1m", "2m", "3m", "4p", "6p", "7s", "8s", "9s", "1s", "1s", "1s", "S", "S"]
    # 待ち牌の "5p" がもう1枚、捨て牌等で場に見えている想定
    visible = tenpai_hand + ["5p"]
    shanten, ukeire = ukeire_for_hand(tenpai_hand, visible_tiles=visible)
    assert shanten == 0
    assert ukeire == 3


def test_find_mistakes_flags_suboptimal_discard() -> None:
    # 3面子+対子(S)+カンチャン(3s5s待ち4s)+孤立牌(E) の14枚。
    # 孤立牌(E)を切ればテンパイ(shanten=0)を維持できるが、
    # 代わりに対子の片方(S)を切るとテンパイを崩してしまう(shanten=1へ悪化)。
    hand14 = ["1m", "2m", "3m", "4p", "5p", "6p", "7s", "8s", "9s", "S", "S", "3s", "5s", "E"]
    events = [
        {
            "type": "start_kyoku",
            "tehais": [hand14, ["?"] * 13, ["?"] * 13, ["?"] * 13],
        },
        {"type": "dahai", "actor": 0, "pai": "S", "tsumogiri": False},
        {"type": "end_kyoku"},
    ]
    mistakes = find_mistakes(_game_log(events))

    assert len(mistakes) == 1
    m = mistakes[0]
    assert m.discarded == "S"
    assert m.best_discard == "E"
    assert m.shanten_after_best == 0
    assert m.is_shanten_loss is True


def test_shanten_loss_that_keeps_a_dora_tile_is_flagged_as_dora_justified() -> None:
    # 上と同じ局面だが、ドラ表示牌を"N"(→ドラは"E")にする。
    # 実際の打牌(S)は孤立牌のE(ドラ)を手元に残すのに対し、最善打(E)はそのドラを
    # 切ってしまう ―― 打点を優先した結果として妥当、と判定されるべきケース。
    hand14 = ["1m", "2m", "3m", "4p", "5p", "6p", "7s", "8s", "9s", "S", "S", "3s", "5s", "E"]
    events = [
        {
            "type": "start_kyoku",
            "tehais": [hand14, ["?"] * 13, ["?"] * 13, ["?"] * 13],
            "dora_marker": "N",
        },
        {"type": "dahai", "actor": 0, "pai": "S", "tsumogiri": False},
        {"type": "end_kyoku"},
    ]
    mistakes = find_mistakes(_game_log(events))

    assert len(mistakes) == 1
    m = mistakes[0]
    assert m.dora_count_actual == 1  # Eを残している
    assert m.dora_count_best == 0  # 最善打(E)を切るとドラが無くなる
    assert m.is_dora_justified_shanten_loss is True


def test_find_mistakes_returns_empty_when_discard_is_optimal() -> None:
    hand14 = ["1m", "2m", "3m", "4p", "5p", "6p", "7s", "8s", "9s", "S", "S", "3s", "5s", "E"]
    events = [
        {
            "type": "start_kyoku",
            "tehais": [hand14, ["?"] * 13, ["?"] * 13, ["?"] * 13],
        },
        {"type": "dahai", "actor": 0, "pai": "E", "tsumogiri": False},
        {"type": "end_kyoku"},
    ]
    mistakes = find_mistakes(_game_log(events))
    assert mistakes == []


def test_find_mistakes_skips_hands_with_unknown_tiles() -> None:
    # 他家(自分以外)の手牌が非公開("?")の場合はスキップされ、ミスとして扱われないこと
    events = [
        {
            "type": "start_kyoku",
            "tehais": [["?"] * 13, ["?"] * 13, ["?"] * 13, ["?"] * 13],
        },
        {"type": "tsumo", "actor": 1, "pai": "1m"},
        {"type": "dahai", "actor": 1, "pai": "9m", "tsumogiri": False},
        {"type": "end_kyoku"},
    ]
    mistakes = find_mistakes(_game_log(events))
    assert mistakes == []


def test_count_dora_counts_indicator_derived_dora() -> None:
    assert count_dora(["4p", "5p", "6p"], dora_markers=["4p"]) == 1  # 4pの次(5p)がドラ


def test_count_dora_counts_aka_dora_regardless_of_indicator() -> None:
    assert count_dora(["5mr", "1p"], dora_markers=["9s"]) == 1  # 赤5mは指示牌と無関係にドラ


def test_count_dora_counts_multiple_copies_and_markers() -> None:
    assert count_dora(["5p", "5p", "E"], dora_markers=["4p", "N"]) == 3  # 5p×2(ドラ)+E(ドラ)


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
        shanten_after_best=2,
        ukeire_after_best=6,
    )
    base.update(overrides)
    return DiscardMistake(**base)


def test_is_dora_justified_shanten_loss_requires_shanten_loss() -> None:
    # シャンテン後退がない(shanten_after_actual == shanten_after_best)場合は、
    # ドラ枚数の差に関わらず「妥当なシャンテン後退」には該当しない。
    m = _mistake(shanten_after_actual=2, shanten_after_best=2, dora_count_actual=2, dora_count_best=0)
    assert m.is_dora_justified_shanten_loss is False


def test_is_dora_justified_shanten_loss_requires_strictly_more_dora() -> None:
    m = _mistake(shanten_after_actual=3, shanten_after_best=2, dora_count_actual=1, dora_count_best=1)
    assert m.is_dora_justified_shanten_loss is False  # 同数では「妥当」とみなさない


def test_is_dora_justified_shanten_loss_true_when_actual_keeps_more_dora() -> None:
    m = _mistake(shanten_after_actual=3, shanten_after_best=2, dora_count_actual=2, dora_count_best=0)
    assert m.is_dora_justified_shanten_loss is True


def test_classify_mistake_shanten_loss_takes_priority() -> None:
    m = _mistake(shanten_after_actual=3, shanten_after_best=2, ukeire_after_actual=1, ukeire_after_best=1)
    assert classify_mistake(m) == MISTAKE_CATEGORY_SHANTEN_LOSS


def test_classify_mistake_major_ukeire_loss() -> None:
    m = _mistake(ukeire_after_actual=2, ukeire_after_best=10)  # loss=8 > 4
    assert classify_mistake(m) == MISTAKE_CATEGORY_MAJOR_UKEIRE_LOSS


def test_classify_mistake_minor_ukeire_loss() -> None:
    m = _mistake(ukeire_after_actual=4, ukeire_after_best=6)  # loss=2 <= 4
    assert classify_mistake(m) == MISTAKE_CATEGORY_MINOR_UKEIRE_LOSS

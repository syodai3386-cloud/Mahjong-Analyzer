"""打牌効率(シャンテン数・受け入れ枚数)に基づくミス検出。

`mahjong`パッケージ(MahjongRepository, MIT)のシャンテン計算を利用する。
自前でシャンテンアルゴリズムを実装しない。

スコープの注意:
  - ここでの「ミス」はあくまで牌効率(シャンテン数・受け入れ枚数)の観点のみ。
    赤ドラの温存や安全牌選択、役の価値判断などは考慮しない(将来拡張の余地)。
  - 受け入れ枚数の計算では、そのプレイヤー自身が打牌を選ぶ時点で実際に
    知り得る情報(自分の手牌・場に見えている捨て牌/副露/ドラ表示牌)だけを
    「見えている牌」として扱う。他家の非公開の手牌は使わない(後知恵を防ぐため)。
"""

from __future__ import annotations

from dataclasses import dataclass

from mahjong.shanten import Shanten

from mahjong_analyzer.parser.model import GameLog, MjaiEvent, iter_kyoku
from mahjong_analyzer.tiles import dora_from_indicator, is_red, tile_from_34, tile_to_34, tiles_to_34_array

_shanten_calculator = Shanten()

# 打牌直前(ツモ後 or 副露後)にあり得る手牌枚数。副露が増えるほど手牌は3枚ずつ減る。
_VALID_PRE_DISCARD_SIZES = {2, 5, 8, 11, 14}

_MELD_TYPES = {"chi", "pon", "kan", "ankan", "kakan"}


@dataclass
class DiscardMistake:
    kyoku_index: int
    turn: int  # そのプレイヤーの局内での打牌巡目(1始まり)
    actor: int
    discarded: str
    shanten_before: int
    shanten_after_actual: int
    ukeire_after_actual: int
    best_discard: str
    shanten_after_best: int
    ukeire_after_best: int
    # 実際の打牌/最善打それぞれを切った後の手牌のドラ枚数(赤ドラ込み)。
    # シャンテン後退が打点重視の結果として妥当か判定するために使う。
    dora_count_actual: int = 0
    dora_count_best: int = 0

    @property
    def is_shanten_loss(self) -> bool:
        return self.shanten_after_actual > self.shanten_after_best

    @property
    def ukeire_loss(self) -> int:
        return max(0, self.ukeire_after_best - self.ukeire_after_actual)

    @property
    def is_dora_justified_shanten_loss(self) -> bool:
        """シャンテン後退が、打点(ドラ枚数)を優先した結果として妥当と言えるか。

        実際に切った牌を残した場合の手牌のドラ枚数が、最善手(効率最優先)を
        切った場合より厳密に多い場合のみ「妥当」とみなす(同点は妥当扱いしない
        ―― それだと単なる見落としと打点重視の区別がつかないため)。
        """
        return self.is_shanten_loss and self.dora_count_actual > self.dora_count_best


# 受け入れ枚数の差がこの枚数以下なら「わずかな見落とし」、これを超えると
# 「大きな見落とし」に分類する。おおよそ「牌1種ぶんの見落とし」を境目にしている
# (1種あたり最大4枚なので、5枚以上は複数種類にまたがる比較ミスとみなせる)。
_MINOR_UKEIRE_LOSS_THRESHOLD = 4

MISTAKE_CATEGORY_SHANTEN_LOSS = "シャンテン後退"
MISTAKE_CATEGORY_MAJOR_UKEIRE_LOSS = "受け入れの大きな見落とし"
MISTAKE_CATEGORY_MINOR_UKEIRE_LOSS = "受け入れのわずかな見落とし"

# severity順(重い順)。UIでの表示順に使う。
MISTAKE_CATEGORIES = [
    MISTAKE_CATEGORY_SHANTEN_LOSS,
    MISTAKE_CATEGORY_MAJOR_UKEIRE_LOSS,
    MISTAKE_CATEGORY_MINOR_UKEIRE_LOSS,
]

MISTAKE_CATEGORY_DESCRIPTIONS = {
    MISTAKE_CATEGORY_SHANTEN_LOSS: "選んだ打牌でシャンテン数自体が悪化した、最も重い失着。",
    MISTAKE_CATEGORY_MAJOR_UKEIRE_LOSS: (
        f"シャンテン数は変わらないが、受け入れ枚数を{_MINOR_UKEIRE_LOSS_THRESHOLD}枚超え損している"
        "(有効牌の比較を大きく見誤っている可能性)。"
    ),
    MISTAKE_CATEGORY_MINOR_UKEIRE_LOSS: (
        f"シャンテン数は変わらず、受け入れ枚数の差も{_MINOR_UKEIRE_LOSS_THRESHOLD}枚以内(僅差の判断ミス)。"
    ),
}


def classify_mistake(mistake: DiscardMistake) -> str:
    """牌効率ミスを重症度で分類する。

    牌効率(シャンテン数・受け入れ枚数)のデータのみから機械的に判定できる範囲の
    分類であり、押し引き(守備)や打点判断は含まない(それらは別軸で評価する)。
    """
    if mistake.is_shanten_loss:
        return MISTAKE_CATEGORY_SHANTEN_LOSS
    if mistake.ukeire_loss > _MINOR_UKEIRE_LOSS_THRESHOLD:
        return MISTAKE_CATEGORY_MAJOR_UKEIRE_LOSS
    return MISTAKE_CATEGORY_MINOR_UKEIRE_LOSS


def hand_shanten(tiles: list[str]) -> int:
    """牌のリスト(mjai風表記)からシャンテン数を計算する。"""
    return _shanten_calculator.calculate_shanten(tiles_to_34_array(tiles))


def ukeire_for_hand(tiles: list[str], visible_tiles: list[str] | None = None) -> tuple[int, int]:
    """手牌の受け入れ枚数を計算する。

    :param tiles: 手牌(mjai風表記のリスト)
    :param visible_tiles: 既に見えている牌(自分の手牌含む)。省略時は手牌のみを見えている牌とみなす。
    :return: (現在のシャンテン数, 受け入れ枚数(残り枚数ベース))
    """
    hand_34 = tiles_to_34_array(tiles)
    visible_34 = tiles_to_34_array(visible_tiles) if visible_tiles is not None else list(hand_34)
    current_shanten = _shanten_calculator.calculate_shanten(hand_34)
    total = _count_ukeire(hand_34, visible_34, current_shanten)
    return current_shanten, total


def _count_ukeire(hand_34: list[int], visible_34: list[int], current_shanten: int) -> int:
    total = 0
    for t in range(34):
        remaining = 4 - visible_34[t]
        if remaining <= 0:
            continue
        hand_34[t] += 1
        shanten_if_drawn = _shanten_calculator.calculate_shanten(hand_34)
        hand_34[t] -= 1
        if shanten_if_drawn < current_shanten:
            total += remaining
    return total


def count_dora(tiles: list[str], dora_markers: list[str]) -> int:
    """手牌のドラ枚数(表ドラ+赤ドラ)を数える。裏ドラは非公開情報なので含めない。"""
    dora_tiles = {dora_from_indicator(marker) for marker in dora_markers}
    count = 0
    for t in tiles:
        if t.rstrip("r") in dora_tiles:
            count += 1
        if is_red(t):
            count += 1
    return count


def _evaluate_discard(
    hand: list[str],
    actual_discard: str,
    public_counts: list[int],
    actor: int,
    kyoku_index: int,
    turn: int,
    dora_markers: list[str],
) -> DiscardMistake | None:
    hand_34 = tiles_to_34_array(hand)
    if sum(hand_34) not in _VALID_PRE_DISCARD_SIZES:
        return None

    shanten_before = _shanten_calculator.calculate_shanten(hand_34)
    visible_34 = [public_counts[i] + hand_34[i] for i in range(34)]

    results: dict[int, tuple[int, int]] = {}
    for kind in (i for i in range(34) if hand_34[i] > 0):
        hand_34[kind] -= 1
        shanten_after = _shanten_calculator.calculate_shanten(hand_34)
        ukeire_after = _count_ukeire(hand_34, visible_34, shanten_after)
        hand_34[kind] += 1
        results[kind] = (shanten_after, ukeire_after)

    actual_kind = tile_to_34(actual_discard)
    if actual_kind not in results:
        return None
    actual_shanten, actual_ukeire = results[actual_kind]

    best_kind = min(results, key=lambda k: (results[k][0], -results[k][1]))
    best_shanten, best_ukeire = results[best_kind]

    if best_kind == actual_kind:
        return None
    if best_shanten < actual_shanten or (best_shanten == actual_shanten and best_ukeire > actual_ukeire):
        hand_after_actual = list(hand)
        _remove_one(hand_after_actual, actual_discard)
        hand_after_best = list(hand)
        _remove_one(hand_after_best, tile_from_34(best_kind))

        return DiscardMistake(
            kyoku_index=kyoku_index,
            turn=turn,
            actor=actor,
            discarded=actual_discard,
            shanten_before=shanten_before,
            shanten_after_actual=actual_shanten,
            ukeire_after_actual=actual_ukeire,
            best_discard=tile_from_34(best_kind),
            shanten_after_best=best_shanten,
            ukeire_after_best=best_ukeire,
            dora_count_actual=count_dora(hand_after_actual, dora_markers),
            dora_count_best=count_dora(hand_after_best, dora_markers),
        )
    return None


def _remove_one(hand: list[str], tile: str) -> None:
    if tile in hand:
        hand.remove(tile)
        return
    # 赤ドラ表記("5mr")と通常表記("5m")の食い違いを許容する
    base = tile.rstrip("r")
    for existing in hand:
        if existing.rstrip("r") == base:
            hand.remove(existing)
            return


def _analyze_kyoku(events: list[MjaiEvent], kyoku_index: int) -> list[DiscardMistake]:
    hands: dict[int, list[str]] = {}
    public_counts = [0] * 34
    turn_counter: dict[int, int] = {}
    dora_markers: list[str] = []
    mistakes: list[DiscardMistake] = []

    def add_public(tile: str) -> None:
        public_counts[tile_to_34(tile)] += 1

    for ev in events:
        etype = ev.get("type")

        if etype == "start_kyoku":
            hands = {i: list(h) for i, h in enumerate(ev.get("tehais", []))}
            marker = ev.get("dora_marker")
            if marker:
                add_public(marker)
                dora_markers = [marker]

        elif etype == "tsumo":
            actor = ev["actor"]
            hands.setdefault(actor, []).append(ev["pai"])

        elif etype == "dahai":
            actor = ev["actor"]
            tile = ev["pai"]
            hand = hands.get(actor)
            if hand is not None and "?" not in hand:
                turn_counter[actor] = turn_counter.get(actor, 0) + 1
                mistake = _evaluate_discard(
                    hand, tile, public_counts, actor, kyoku_index, turn_counter[actor], dora_markers
                )
                if mistake is not None:
                    mistakes.append(mistake)
                _remove_one(hand, tile)
            add_public(tile)

        elif etype in _MELD_TYPES:
            actor = ev["actor"]
            hand = hands.get(actor)
            for consumed_tile in ev.get("consumed", []):
                if hand is not None:
                    _remove_one(hand, consumed_tile)
                add_public(consumed_tile)

        elif etype == "dora":
            marker = ev.get("dora_marker")
            if marker:
                add_public(marker)
                dora_markers.append(marker)

    return mistakes


def find_mistakes(game_log: GameLog) -> list[DiscardMistake]:
    """対局全体の打牌ミス(効率観点)を検出する。"""
    mistakes: list[DiscardMistake] = []
    for kyoku_index, kyoku_events in enumerate(iter_kyoku(game_log.events)):
        mistakes.extend(_analyze_kyoku(kyoku_events, kyoku_index))
    return mistakes

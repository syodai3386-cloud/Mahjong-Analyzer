"""mjai風の牌表記(例: "4p", "5mr", "E")と`mahjong`パッケージが使う34種配列との変換ユーティリティ。

mjai表記:
  - 数牌: "<1-9><m|p|s>" (例: "4p" = ピンズの4)
  - 赤ドラ: 末尾に "r" (例: "5mr" = 赤五萬)
  - 字牌: "E","S","W","N" (風) / "P","F","C" (白發中)

`mahjong`パッケージの34インデックス順序:
  0-8   = 1m-9m
  9-17  = 1p-9p
  18-26 = 1s-9s
  27-33 = 東南西北白發中 (E,S,W,N,P,F,C)
"""

from __future__ import annotations

SUITS = "mps"
HONORS = ["E", "S", "W", "N", "P", "F", "C"]


def is_honor(tile: str) -> bool:
    base = tile.rstrip("r")
    return base in HONORS


def is_red(tile: str) -> bool:
    return tile.endswith("r")


def tile_to_34(tile: str) -> int:
    """mjai風の牌表記を34インデックスに変換する。"""
    base = tile.rstrip("r") if tile.endswith("r") else tile
    if base in HONORS:
        return 27 + HONORS.index(base)
    if len(base) != 2 or base[1] not in SUITS:
        raise ValueError(f"不正な牌表記です: {tile!r}")
    rank = int(base[0])
    if not (1 <= rank <= 9):
        raise ValueError(f"不正な牌表記です: {tile!r}")
    suit_offset = SUITS.index(base[1]) * 9
    return suit_offset + (rank - 1)


def tile_from_34(index: int) -> str:
    """34インデックスを代表的なmjai風牌表記に変換する(赤ドラ情報は失われる)。"""
    if not (0 <= index <= 33):
        raise ValueError(f"不正な34インデックスです: {index}")
    if index >= 27:
        return HONORS[index - 27]
    suit = SUITS[index // 9]
    rank = index % 9 + 1
    return f"{rank}{suit}"


def tiles_to_34_array(tiles: list[str]) -> list[int]:
    """牌のリストを34要素の枚数配列に変換する。"""
    counts = [0] * 34
    for tile in tiles:
        counts[tile_to_34(tile)] += 1
    return counts


def all_tile_strings() -> list[str]:
    """34種すべての代表牌表記(赤ドラなし)を返す。"""
    return [tile_from_34(i) for i in range(34)]


_WIND_ORDER = ["E", "S", "W", "N"]
_DRAGON_ORDER = ["P", "F", "C"]  # 白(P)→發(F)→中(C)


def dora_from_indicator(indicator: str) -> str:
    """ドラ表示牌から実際のドラ牌を求める(数牌は次の数、字牌は各グループ内を巡回)。"""
    base = indicator.rstrip("r")
    if base in _WIND_ORDER:
        return _WIND_ORDER[(_WIND_ORDER.index(base) + 1) % len(_WIND_ORDER)]
    if base in _DRAGON_ORDER:
        return _DRAGON_ORDER[(_DRAGON_ORDER.index(base) + 1) % len(_DRAGON_ORDER)]
    rank = int(base[0])
    suit = base[1]
    next_rank = rank % 9 + 1
    return f"{next_rank}{suit}"

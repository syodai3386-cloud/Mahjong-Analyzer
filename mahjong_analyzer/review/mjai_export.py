"""内部イベント形式(parser.model、mjai風)を、Mortalが要求するmjaiプロトコルの
JSON Linesに変換する。

視点マスキング(ここが正しくないとMortalの判断が後知恵になり、比較の意味が
なくなる):
  - レビュー対象プレイヤー(perspective_seat)以外の配牌(start_kyoku.tehais)は
    "?" で伏せる。
  - perspective_seat以外のプレイヤーのツモ牌(tsumo.pai)も、打牌されるまでは
    他家から見えない情報なので "?" で伏せる。
  - 打牌・副露・リーチ宣言・和了・ドラ表示は卓上で公開される情報なので伏せない。

mjaiプロトコルの正式仕様のうち未確認の部分(例: start_gameの厳密なフィールド)
は、公式ドキュメント抜粋で確認できた範囲(start_game/start_kyoku/tsumo/dahai/
pon/reach、およびMortal公式Dockerの `docker run ... mortal <seat> < log.json`
がseatをCLI引数で受け取る点)に基づくベストエフォート実装。実際にMortalを
動かして出力を検証できる環境(RAM増設後)で最終確認が必要。
"""

from __future__ import annotations

import json

from mahjong_analyzer.parser.model import GameLog, MjaiEvent

HIDDEN_TILE = "?"

_UNMASKED_EVENT_TYPES = {
    "dahai",
    "chi",
    "pon",
    "kan",
    "ankan",
    "kakan",
    "reach",
    "hora",
    "ryukyoku",
    "dora",
    "end_kyoku",
    "end_game",
}


def _mask_tehais(tehais: list[list[str]], perspective_seat: int) -> list[list[str]]:
    return [
        list(hand) if seat == perspective_seat else [HIDDEN_TILE] * len(hand)
        for seat, hand in enumerate(tehais)
    ]


def _mask_event(ev: MjaiEvent, perspective_seat: int) -> MjaiEvent:
    etype = ev.get("type")

    if etype == "start_kyoku":
        masked = dict(ev)
        masked["tehais"] = _mask_tehais(ev.get("tehais", []), perspective_seat)
        return masked

    if etype == "tsumo":
        if ev.get("actor") == perspective_seat:
            return dict(ev)
        masked = dict(ev)
        masked["pai"] = HIDDEN_TILE
        return masked

    if etype in _UNMASKED_EVENT_TYPES:
        return dict(ev)

    return dict(ev)


def to_mjai_events(game_log: GameLog, perspective_seat: int) -> list[MjaiEvent]:
    """指定席(perspective_seat)から見えるmjaiイベント列を生成する。"""
    names = [game_log.player_name(seat) for seat in range(4)]
    events: list[MjaiEvent] = [{"type": "start_game", "names": names}]
    events.extend(_mask_event(ev, perspective_seat) for ev in game_log.events)
    return events


def to_mjai_jsonl(game_log: GameLog, perspective_seat: int) -> str:
    """Mortalプロセスへの標準入力として渡す、改行区切りJSON文字列を生成する。"""
    lines = [json.dumps(ev, ensure_ascii=False) for ev in to_mjai_events(game_log, perspective_seat)]
    return "\n".join(lines) + "\n"

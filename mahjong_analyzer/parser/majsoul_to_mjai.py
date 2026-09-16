"""雀魂rawレコード(fetcher.downloaderが保存したJSON)を、mjai風の正規化イベント列に変換する。

牌表記の変換:
  雀魂表記 "0m/0p/0s"(赤ドラ) → mjai表記 "5mr/5pr/5sr"
  雀魂表記 "1z".."7z"(字牌: 東南西北白發中) → mjai表記 "E","S","W","N","P","F","C"
  それ以外の数牌(例: "4p")はそのまま。

不確実性についての注意:
  - RecordChiPengGang.type (0=チー/1=ポン/2=カン) はコミュニティで広く採用されている
    慣行に基づく推測。実データで挙動が異なる場合は調整が必要。
  - ロン時の放銃者(target)は、直前のRecordDiscardTileの打牌者として推定している
    (HuleInfo自体には放銃者情報が含まれないため)。
"""

from __future__ import annotations

from typing import Any

from mahjong_analyzer.parser.model import GameLog, MjaiEvent, PlayerInfo

_HONOR_MAP = {"1z": "E", "2z": "S", "3z": "W", "4z": "N", "5z": "P", "6z": "F", "7z": "C"}
_BAKAZE_MAP = {0: "E", 1: "S", 2: "W"}
_CALL_TYPE_MAP = {0: "chi", 1: "pon", 2: "kan"}


def _tile(tile: str | None) -> str | None:
    if not tile:
        return None
    if tile in _HONOR_MAP:
        return _HONOR_MAP[tile]
    if len(tile) == 2 and tile[0] == "0" and tile[1] in "mps":
        return f"5{tile[1]}r"
    return tile


def _tiles(tiles: list[str] | None) -> list[str]:
    return [t for t in (_tile(x) for x in (tiles or [])) if t is not None]


def _split_concat_tiles(concat: str) -> list[str]:
    return [concat[i : i + 2] for i in range(0, len(concat), 2)]


def _build_players(head: dict[str, Any]) -> list[PlayerInfo]:
    accounts = head.get("accounts", [])
    players = [
        PlayerInfo(
            seat=a.get("seat", i),
            name=a.get("nickname") or f"seat{a.get('seat', i)}",
            account_id=a.get("account_id"),
        )
        for i, a in enumerate(accounts)
    ]
    known_seats = {p.seat for p in players}
    for seat in range(4):
        if seat not in known_seats:
            players.append(PlayerInfo(seat=seat, name=f"seat{seat}"))
    players.sort(key=lambda p: p.seat)
    return players


def _final_scores(head: dict[str, Any]) -> list[int] | None:
    result = head.get("result", {})
    items = result.get("players", [])
    if not items:
        return None
    by_seat = {item.get("seat", i): item.get("total_point", 0) for i, item in enumerate(items)}
    return [by_seat.get(seat, 0) for seat in range(4)]


def convert(raw: dict[str, Any]) -> GameLog:
    """downloader.download_game_recordが返した(または保存したJSONを読み込んだ)dictを変換する。"""
    head = raw.get("head", {})
    players = _build_players(head)

    events: list[MjaiEvent] = []
    last_discard_seat: int | None = None
    kyoku_open = False

    for rec in raw.get("records", []):
        name = rec.get("name")
        data = rec.get("data")
        if data is None:
            continue

        if name == ".lq.RecordNewRound":
            if kyoku_open:
                events.append({"type": "end_kyoku"})
            chang = data.get("chang", 0)
            ju = data.get("ju", 0)
            tehais = [_tiles(data.get(f"tiles{seat}")) for seat in range(4)]
            dora = data.get("dora")
            events.append(
                {
                    "type": "start_kyoku",
                    "bakaze": _BAKAZE_MAP.get(chang, "E"),
                    "kyoku": ju + 1,
                    "honba": data.get("ben", 0),
                    "kyotaku": data.get("liqibang", 0),
                    "oya": ju % 4,
                    "dora_marker": _tile(dora),
                    "tehais": tehais,
                    "scores": data.get("scores", []),
                }
            )
            kyoku_open = True
            last_discard_seat = None

        elif name == ".lq.RecordDealTile":
            seat = data.get("seat", 0)
            tile = _tile(data.get("tile"))
            if tile is not None:
                events.append({"type": "tsumo", "actor": seat, "pai": tile})

        elif name == ".lq.RecordDiscardTile":
            seat = data.get("seat", 0)
            tile = _tile(data.get("tile"))
            if tile is None:
                continue
            events.append(
                {
                    "type": "dahai",
                    "actor": seat,
                    "pai": tile,
                    "tsumogiri": bool(data.get("moqie", False)),
                }
            )
            if data.get("is_liqi"):
                events.append({"type": "reach", "actor": seat})
            last_discard_seat = seat

        elif name == ".lq.RecordChiPengGang":
            seat = data.get("seat", 0)
            tiles = data.get("tiles", [])
            froms = data.get("froms", [])
            call_type = _CALL_TYPE_MAP.get(data.get("type", 1), "pon")

            consumed: list[str] = []
            pai: str | None = None
            target: int | None = None
            for tile, frm in zip(tiles, froms):
                if frm == seat:
                    mapped = _tile(tile)
                    if mapped is not None:
                        consumed.append(mapped)
                else:
                    pai = _tile(tile)
                    target = frm

            ev: MjaiEvent = {"type": call_type, "actor": seat, "consumed": consumed}
            if pai is not None:
                ev["pai"] = pai
            if target is not None:
                ev["target"] = target
            events.append(ev)

        elif name == ".lq.RecordAnGangAddGang":
            seat = data.get("seat", 0)
            tiles = _split_concat_tiles(data.get("tiles", ""))
            call_type = "ankan" if len(tiles) >= 4 else "kakan"
            events.append({"type": call_type, "actor": seat, "consumed": _tiles(tiles)})

            new_doras = data.get("doras")
            if new_doras:
                marker = _tile(new_doras[-1])
                if marker is not None:
                    events.append({"type": "dora", "dora_marker": marker})

        elif name == ".lq.RecordHule":
            deltas = data.get("delta_scores")
            scores_after = data.get("scores")
            for hule in data.get("hules", []):
                actor = hule.get("seat", 0)
                is_tsumo = bool(hule.get("zimo", False))
                target = actor if is_tsumo else (last_discard_seat if last_discard_seat is not None else actor)
                events.append(
                    {
                        "type": "hora",
                        "actor": actor,
                        "target": target,
                        "pai": _tile(hule.get("hu_tile")),
                        "deltas": deltas,
                        "scores": scores_after,
                    }
                )

        elif name in (".lq.RecordNoTile", ".lq.RecordLiuJu"):
            events.append({"type": "ryukyoku", "reason": name.rsplit(".", 1)[-1]})

    if kyoku_open:
        events.append({"type": "end_kyoku"})

    final_scores = _final_scores(head)
    if final_scores is not None:
        events.append({"type": "end_game", "scores": final_scores})

    return GameLog(
        paipu_id=raw.get("uuid", head.get("uuid", "")),
        players=players,
        events=events,
        start_time=head.get("start_time"),
        end_time=head.get("end_time"),
    )

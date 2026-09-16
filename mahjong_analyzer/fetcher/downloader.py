"""雀魂の対局履歴一覧取得・牌譜本体のダウンロードとJSON保存。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from google.protobuf.json_format import MessageToDict

sys.path.insert(0, str(Path(__file__).parent / "proto"))
import liqi_pb2 as pb  # type: ignore  # noqa: E402

from mahjong_analyzer.fetcher.client import MajsoulApiError, MajsoulClient


def _to_dict(message: Any) -> dict[str, Any]:
    """protobufメッセージをdictに変換する。

    デフォルト値(0や空文字列など)のフィールドが省略されると、例えば
    「席0のプレイヤー」の seat フィールドが消えて席の対応がズレるバグに
    繋がるため、always_print_fields_with_no_presence=True で必ず含める。
    """
    return MessageToDict(
        message, always_print_fields_with_no_presence=True, preserving_proto_field_name=True
    )

# 牌譜内の各局イベント(Wrapperのname)と対応するメッセージ型。
# 未知のnameは "data": None のまま保存され、パーサー側でスキップされる。
_RECORD_TYPES: dict[str, Any] = {
    ".lq.RecordNewRound": pb.RecordNewRound,
    ".lq.RecordDiscardTile": pb.RecordDiscardTile,
    ".lq.RecordDealTile": pb.RecordDealTile,
    ".lq.RecordChiPengGang": pb.RecordChiPengGang,
    ".lq.RecordAnGangAddGang": pb.RecordAnGangAddGang,
    ".lq.RecordBaBei": pb.RecordBaBei,
    ".lq.RecordHule": pb.RecordHule,
    ".lq.RecordNoTile": pb.RecordNoTile,
    ".lq.RecordLiuJu": pb.RecordLiuJu,
}


def _extract_records(details: "pb.GameDetailRecords") -> list[dict[str, Any]]:
    """GameDetailRecordsから局内イベント列を取り出す。

    雀魂には2種類の格納形式がある:
      - 旧形式: `records`(Wrapper{name,data}をSerializeToStringしたbytesのリスト)
      - 新形式: `actions`(GameAction{type, result, user_input, user_event, ...}のリスト)。
        実機キャプチャで確認したところ、type=1のアクションのresultフィールドに
        旧形式と全く同じWrapper{name,data}(.lq.RecordDiscardTile等)が入っている。
        type=2(user_input)/type=3(user_event)/type=4(区切り)は、誰が何を捨てたか等の
        状態変化そのものではなく操作ログ/UI用イベントなので無視してよい。
    """
    raw_wrappers: list[bytes] = list(details.records)
    if not raw_wrappers:
        raw_wrappers = [action.result for action in details.actions if action.result]

    records: list[dict[str, Any]] = []
    for raw in raw_wrappers:
        inner = pb.Wrapper()
        try:
            inner.ParseFromString(raw)
        except Exception:  # noqa: BLE001 - resultには稀に無関係なバイト列も混ざる
            continue
        record_class = _RECORD_TYPES.get(inner.name)
        if record_class is None:
            records.append({"name": inner.name, "data": None})
            continue
        message = record_class()
        message.ParseFromString(inner.data)
        records.append({"name": inner.name, "data": _to_dict(message)})
    return records


async def list_recent_games(client: MajsoulClient, count: int = 10) -> list[dict[str, Any]]:
    """自分の直近の対局一覧(牌譜メタ情報)を取得する。"""
    req = pb.ReqGameRecordList()
    req.start = 0
    req.count = count
    res = await client.call("fetchGameRecordList", req)
    if res.error.code:
        raise MajsoulApiError(res.error)
    return [_to_dict(r) for r in res.record_list]


async def download_game_record(client: MajsoulClient, game_uuid: str) -> dict[str, Any]:
    """牌譜1局(1半荘)分の詳細を取得し、head(メタ情報)とrecords(局内イベント列)を返す。"""
    req = pb.ReqGameRecord()
    req.game_uuid = game_uuid
    res = await client.call("fetchGameRecord", req)
    if res.error.code:
        raise MajsoulApiError(res.error)

    outer = pb.Wrapper()
    outer.ParseFromString(res.data)
    details = pb.GameDetailRecords()
    details.ParseFromString(outer.data)

    records = _extract_records(details)
    if not records:
        raise RuntimeError(
            "この牌譜からイベントを1件も抽出できませんでした"
            "(records・actionsのどちらも空か、未知の形式です)。"
        )

    return {
        "uuid": game_uuid,
        "head": _to_dict(res.head),
        "records": records,
    }


def save_raw_record(record: dict[str, Any], raw_dir: Path) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{record['uuid']}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path

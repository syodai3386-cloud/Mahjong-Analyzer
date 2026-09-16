"""mitmproxyアドオン: 雀魂の対局データを一括取得する。

2つの仕組みを持つ:
  1. 受動キャプチャ: 実際のクライアント(ブラウザ)が発行する fetchGameRecord の
     レスポンスをリアルタイムで検知し、data/raw/ にJSONとして保存する。
  2. 能動注入(本命): 既にログイン済みの正規のWebSocket接続に対して、
     `inject.websocket` を使い、このアドオン自身が fetchGameRecordListV2 /
     fetchNextGameRecordList / fetchGameRecord を直接注入して送信する。
     これにより、UIのクリックや演出の読み込みを待つ必要が一切なくなり、
     牌譜一覧の取得から全対局のダウンロードまでを完全自動・高速に行える。
     (雀魂側のサーバーに負荷をかけすぎない・不正利用と誤検知されないよう、
     PACING_SECONDS で送信間隔を空けている)

使い方:
    mitmdump -s record_capture_addon.py --listen-port 8080
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from mitmproxy import ctx

sys.path.insert(0, str(Path(__file__).parent.parent / "mahjong_analyzer" / "fetcher" / "proto"))
import liqi_pb2 as pb  # type: ignore  # noqa: E402
from google.protobuf.json_format import MessageToDict  # noqa: E402

OUT_DIR = Path(__file__).parent.parent / "data" / "raw"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 雀魂サーバーに負荷をかけすぎたり、不正な連続アクセスと誤検知されたりしないよう、
# 注入するリクエストの間隔を空ける。
# 実測: 1.5秒間隔では約4回に3回が error code=540(レート制限と思われる)で失敗した。
# 安全マージンを見て6.5秒に設定(アカウントへのリスクを避けることを優先)。
PACING_SECONDS = 6.5
RETRY_PACING_SECONDS = 10.0

_CLIENT_VERSION_STRING = "WebGL_2022-0.16.259"

_running_tasks: set[asyncio.Task] = set()


def _to_dict(message: Any) -> dict[str, Any]:
    """デフォルト値(0など)のフィールドが省略されないようにしてdict化する。

    (例: 席0のプレイヤーの seat フィールドが消えてしまうバグを防ぐ)
    """
    return MessageToDict(
        message, always_print_fields_with_no_presence=True, preserving_proto_field_name=True
    )


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

# ログイン完了を検知するためのRPC名(このレスポンスが正常に返ってきたら
# 一括取得を開始してよいと判断する)。
_LOGIN_METHODS = {".lq.Lobby.oauth2Login", ".lq.Lobby.emailLogin", ".lq.Lobby.login"}


class GameRecordCapture:
    def __init__(self) -> None:
        self._pending: dict[tuple[str, int], str] = {}
        self._response_futures: dict[tuple[str, int], asyncio.Future] = {}
        self._saved: set[str] = {p.stem for p in OUT_DIR.glob("*.json")}
        self._next_idx = 1
        self._last_real_idx = 0
        # 雀魂クライアントはログイン直後に接続を張り直すことがあるため、
        # 特定のflowオブジェクトを保持せず「今アクティブな接続」を常に参照する。
        self._latest_flow: Any = None
        self._bulk_task_active = False
        self._login_ready_event = asyncio.Event()
        print(f"[capture] 起動しました。既存の保存済み牌譜: {len(self._saved)}件")

    # ------------------------------------------------------------------
    # 受動キャプチャ(実クライアントの通信を横取りして保存する部分)
    # ------------------------------------------------------------------

    def websocket_message(self, flow) -> None:  # noqa: ANN001
        host = getattr(flow.request, "host", "") or ""
        if "mahjongsoul.com" not in host or flow.request.path != "/gateway":
            return
        if not flow.websocket.messages:
            return

        msg = flow.websocket.messages[-1]
        content = msg.content
        if not content or len(content) < 3:
            return

        type_byte = content[0]
        key = (flow.id, int.from_bytes(content[1:3], "little"))

        if type_byte == 2:  # REQUEST
            wrapper = pb.Wrapper()
            wrapper.ParseFromString(content[3:])
            if key not in self._pending:
                # 自分がinjectしたリクエストは事前にpendingへ登録済みなので、
                # ここに来るのは実クライアント自身が発行したリクエストのみ。
                self._last_real_idx = max(self._last_real_idx, key[1])
            self._pending[key] = wrapper.name

        elif type_byte == 3:  # RESPONSE
            name = self._pending.pop(key, None)

            fut = self._response_futures.pop(key, None)
            if fut is not None and not fut.done():
                fut.set_result(content[3:])

            if name in _LOGIN_METHODS:
                res_wrapper = pb.Wrapper()
                res_wrapper.ParseFromString(content[3:])
                res = pb.ResLogin()
                res.ParseFromString(res_wrapper.data)
                if not res.error.code:
                    self._login_ready_event.set()
                    print("[capture] ログイン検知(既存クライアントのセッション) -> 一括取得を開始します")

            if name != ".lq.Lobby.fetchGameRecord":
                return
            self._handle_game_record(content[3:])

    def _extract_records(self, details) -> list[dict[str, Any]]:  # noqa: ANN001
        """GameDetailRecordsから局内イベント列を取り出す。

        雀魂には2種類の格納形式がある:
          - 旧形式: `records`(Wrapper{name,data}のbytesのリスト)
          - 新形式: `actions`(GameAction{type,result,user_input,user_event,...}のリスト)。
            実機キャプチャで確認したところ、type=1のアクションのresultフィールドに
            旧形式と全く同じWrapper{name,data}(.lq.RecordDiscardTile等)が入っている。
            type=2(user_input)/type=3(user_event)/type=4(区切り)は操作ログ/UI用
            イベントなので無視してよい。
        """
        raw_wrappers: list[bytes] = list(details.records)
        if not raw_wrappers:
            raw_wrappers = [action.result for action in details.actions if action.result]

        records: list[dict[str, Any]] = []
        for raw in raw_wrappers:
            inner = pb.Wrapper()
            try:
                inner.ParseFromString(raw)
            except Exception:  # noqa: BLE001
                continue
            record_class = _RECORD_TYPES.get(inner.name)
            if record_class is None:
                records.append({"name": inner.name, "data": None})
                continue
            message = record_class()
            message.ParseFromString(inner.data)
            records.append({"name": inner.name, "data": _to_dict(message)})
        return records

    def _handle_game_record(self, wrapped: bytes) -> None:
        wrapper = pb.Wrapper()
        wrapper.ParseFromString(wrapped)
        res = pb.ResGameRecord()
        res.ParseFromString(wrapper.data)
        if res.error.code:
            print(f"[capture] fetchGameRecord error code={res.error.code}")
            return

        uuid = res.head.uuid
        if uuid in self._saved:
            print(f"[capture] skip (already saved): {uuid}")
            return

        outer = pb.Wrapper()
        outer.ParseFromString(res.data)
        details = pb.GameDetailRecords()
        details.ParseFromString(outer.data)

        records = self._extract_records(details)
        if not records:
            print(f"[capture] {uuid}: records/actionsのどちらからもイベントを抽出できませんでした")
            return

        out = {
            "uuid": uuid,
            "head": _to_dict(res.head),
            "records": records,
        }
        path = OUT_DIR / f"{uuid}.json"
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        self._saved.add(uuid)
        print(f"[capture] saved {uuid} ({len(records)} records) -> {path}")

    # ------------------------------------------------------------------
    # 能動注入(本命: 既存の認証済み接続に直接リクエストを送り込む部分)
    # ------------------------------------------------------------------

    def _alloc_idx(self) -> int:
        # 実クライアント自身の直近のidxに続く番号を使う(大きく飛んだ番号は
        # サーバー側で無効と判断される可能性があったため、念のため踏襲している)。
        idx = max(self._next_idx, self._last_real_idx + 1)
        self._next_idx = (idx + 1) % 60007
        return idx

    async def _send_and_wait(
        self, method: str, request_message: Any, timeout: float = 20, raw_data: bytes | None = None
    ) -> bytes | None:
        """Lobbyサービスにリクエストを注入し、レスポンス(Wrapperの中身)を待つ。

        注入先は呼び出し時点の self._latest_flow(今アクティブな接続)。
        raw_data を渡すと、request_message.SerializeToString() の代わりに
        そのバイト列をそのまま使う(デバッグ用: 実機キャプチャの生バイトと比較するため)。
        """
        flow = self._latest_flow
        if flow is None or flow.websocket is None or flow.websocket.timestamp_end is not None:
            print(f"[capture] bulk: {method} を送れませんでした(有効な接続がありません)")
            return None

        idx = self._alloc_idx()
        name = f".lq.Lobby.{method}"
        data = raw_data if raw_data is not None else request_message.SerializeToString()
        wrapper = pb.Wrapper(name=name, data=data)
        packet = b"\x02" + idx.to_bytes(2, "little") + wrapper.SerializeToString()
        key = (flow.id, idx)

        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[key] = name
        self._response_futures[key] = fut

        # inject_websocket(flow, to_client, message, is_text) — to_client=False で
        # クライアント→サーバー方向、is_text=False でバイナリフレームとして送る。
        # (第2引数を"from_client"だと誤解して逆方向のテキストフレームを送っていたのが
        # これまでタイムアウトしていた根本原因だった)
        ctx.master.commands.call("inject.websocket", flow, False, packet, False)

        try:
            raw = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            print(f"[capture] bulk: {method} がタイムアウトしました")
            return None
        finally:
            self._pending.pop(key, None)
            self._response_futures.pop(key, None)

        res_wrapper = pb.Wrapper()
        res_wrapper.ParseFromString(raw)
        return res_wrapper.data

    def websocket_start(self, flow) -> None:  # noqa: ANN001
        host = getattr(flow.request, "host", "") or ""
        # バックアップ接続(jpgsbk等)ではログインが行われないため、
        # プライマリのゲートウェイ(jpgs.mahjongsoul.com)だけを対象にする。
        if not host.startswith("jpgs.") or "mahjongsoul.com" not in host:
            return
        if flow.request.path != "/gateway":
            return

        print(f"[capture] 新しいプライマリ接続を検知 flow.id={flow.id}")
        self._latest_flow = flow
        # 接続が張り直された場合に備え、ログイン検知も引き継がずリセットする。
        self._login_ready_event = asyncio.Event()

        if self._bulk_task_active:
            return
        self._bulk_task_active = True
        task = asyncio.create_task(self._bulk_fetch_all())
        _running_tasks.add(task)
        task.add_done_callback(lambda t: (_running_tasks.discard(t), setattr(self, "_bulk_task_active", False)))

    async def _wait_for_login(self, timeout: float = 90) -> bool:
        try:
            await asyncio.wait_for(self._login_ready_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def _discover_uuids(self) -> list[str]:
        req = pb.ReqGameRecordListV2()
        req.ranks.extend([1, 2, 3, 4])
        req.modes.extend([3, 4])
        req.level_mode.extend([1, 2, 3, 4, 6])
        raw = await self._send_and_wait("fetchGameRecordListV2", req)
        if raw is None:
            return []
        res = pb.ResGameRecordListV2()
        res.ParseFromString(raw)
        if res.error.code:
            print(f"[capture] bulk: fetchGameRecordListV2 error code={res.error.code}")
            return []

        iterator = res.iterator
        uuids: list[str] = []
        while True:
            req2 = pb.ReqNextGameRecordList()
            req2.iterator = iterator
            req2.count = 100
            raw2 = await self._send_and_wait("fetchNextGameRecordList", req2)
            if raw2 is None:
                break
            res2 = pb.ResNextGameRecordList()
            res2.ParseFromString(raw2)
            if res2.error.code:
                print(f"[capture] bulk: fetchNextGameRecordList error code={res2.error.code}")
                break
            uuids.extend(entry.uuid for entry in res2.entries)
            print(f"[capture] bulk: 対局一覧を取得中... 現在{len(uuids)}件 (next={res2.next})")
            if not res2.next:
                break
            await asyncio.sleep(PACING_SECONDS)
        return uuids

    async def _bulk_fetch_all(self) -> None:
        print("[capture] bulk: ログイン完了を待っています...")
        if not await self._wait_for_login():
            print("[capture] bulk: ログインを検知できませんでした(タイムアウト)。一括取得を中止します。")
            return

        # ログイン直後は接続が張り直されることがあるため、少し待って
        # self._latest_flow が安定するのを待つ。
        await asyncio.sleep(5)

        print("[capture] bulk: 対局一覧の取得を開始します...")
        uuids = await self._discover_uuids()
        print(f"[capture] bulk: 合計{len(uuids)}件の対局を発見しました")

        todo = [u for u in uuids if u not in self._saved]
        print(f"[capture] bulk: {len(todo)}件が未取得です(取得済み{len(uuids) - len(todo)}件はスキップ)")

        failed = await self._fetch_batch(todo, PACING_SECONDS, "本取得")

        if failed:
            print(f"[capture] bulk: {len(failed)}件が失敗したため、間隔を広げて再試行します...")
            still_failed = await self._fetch_batch(failed, RETRY_PACING_SECONDS, "再試行")
            if still_failed:
                print(f"[capture] bulk: 再試行後も失敗: {len(still_failed)}件 -> {still_failed}")

        print(f"[capture] bulk: 完了。保存済み合計 {len(self._saved)} 件")

    async def _fetch_batch(self, uuids: list[str], pacing: float, label: str) -> list[str]:
        """uuidsを順番に(awaitして)取得し、失敗したuuidのリストを返す。"""
        failed: list[str] = []
        for i, uuid in enumerate(uuids):
            req = pb.ReqGameRecord()
            req.game_uuid = uuid
            req.client_version_string = _CLIENT_VERSION_STRING
            await self._send_and_wait("fetchGameRecord", req, timeout=30)
            ok = uuid in self._saved
            if not ok:
                failed.append(uuid)
            print(f"[capture] bulk[{label}]: [{i + 1}/{len(uuids)}] {uuid} {'OK' if ok else 'FAILED'}")
            await asyncio.sleep(pacing)
        return failed


addons = [GameRecordCapture()]

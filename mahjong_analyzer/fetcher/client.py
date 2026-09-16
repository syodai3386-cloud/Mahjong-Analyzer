"""雀魂(MahjongSoul)のWebSocket + Protobuf非公式APIへの低レベル接続クライアント。

これは非公式・未ドキュメント化のAPIであり、サーバー側の仕様変更で動作しなくなる
可能性がある。実装はコミュニティで広く共有されているプロトコル定義(liqi.proto)を
参考にしている。

日本版(Yostarアカウント)のログイン方式は、mitmproxyで実際のログイン通信を
キャプチャして解析した結果、以下の3段階のフローであることを実機で確認済み:

  1. oauth2Auth(type=21, code=<yostar_token>, uid=<yostar_uid>) -> 一時的なaccess_tokenを取得
  2. oauth2Check(type=21, access_token=<上記>) -> アカウント存在確認(形式的なステップ)
  3. oauth2Login(type=21, access_token=<上記>, ...) -> ログイン成功

`yostar_token`/`yostar_uid`はブラウザのLocal Storage(https://game.mahjongsoul.com)
にある同名のキーから取得できる。`type=21`や`random_key`をdevice_idに一致させる必要が
あった点、`client_version`がstring一発ではなくClientVersionInfoサブメッセージである点は
実際の通信を見るまで分からなかった(コミュニティのCN向けサンプルコードには無い情報)。
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import random
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import aiohttp
import websockets

sys.path.insert(0, str(Path(__file__).parent / "proto"))
import liqi_pb2 as pb  # type: ignore  # noqa: E402

_SERVER_HOSTS = {
    "cn": "https://game.maj-soul.com",
    "jp": "https://game.mahjongsoul.com",
    "en": "https://mahjongsoul.game.yo-star.com",
}

# 2026年3月のYostarアカウント移行でJP/EN版クライアントはUnity WebGL化され、
# 旧来の version.json → config.json → サーバー一覧 というHTTP経由の発見手順が
# 403で機能しなくなっていることを実機のブラウザコンソールログで確認した。
# JPについてはコンソールログに出力される "WS_Create(wss://jpgs.mahjongsoul.com:443/gateway, ...)"
# から実際のゲートウェイホストを直接特定できたため、既知ホストとしてハードコードする。
# (プライマリ接続に失敗した場合はバックアップホストにフォールバックする)
# CN版は旧方式のHTTP発見手順がまだ有効であることを確認済み。
# EN(グローバル)版は未検証(JPと同様にブラウザで実機確認すれば特定できるはず)。
_KNOWN_GATEWAYS: dict[str, list[str]] = {
    "jp": ["jpgs.mahjongsoul.com", "jpgsbk.mahjongsoul.com"],
}

# 既知ゲートウェイを使う場合はversion.jsonが引けないため、実機キャプチャ(2026年9月)で
# 確認できた実際のバージョン文字列を暫定値とする。ゲーム更新で変わる可能性がある。
_FALLBACK_CLIENT_VERSION = {"jp": "4.0.12"}
_CLIENT_VERSION_STRING = {"jp": "WebGL_2022-0.16.259"}
_CLIENT_VERSION_RESOURCE = {"jp": "0.16.259"}

# 実機キャプチャで確認した、日本(Yostar)版アカウントのoauth2Auth/oauth2Login用type値。
_YOSTAR_TYPE = 21

_PASSWORD_HMAC_KEY = b"lailai"

_RESPONSE_TYPES: dict[str, Any] = {
    "Lobby.emailLogin": pb.ResLogin,
    "Lobby.oauth2Login": pb.ResLogin,
    "Lobby.oauth2Auth": pb.ResOauth2Auth,
    "Lobby.oauth2Check": pb.ResOauth2Check,
    "Lobby.fetchGameRecordList": pb.ResGameRecordList,
    "Lobby.fetchGameRecord": pb.ResGameRecord,
    "Route.requestConnection": pb.ResRequestConnection,
    "Route.heartbeat": pb.ResHeartbeat,
}

# 実機キャプチャで確認した、requestConnectionのroute_id(地域識別子)。
_ROUTE_ID = {"jp": "jp-1"}


class MajsoulApiError(RuntimeError):
    """雀魂APIがエラーレスポンスを返した場合の例外。"""

    def __init__(self, error: "pb.Error") -> None:
        self.code = error.code
        self.error = error
        super().__init__(f"雀魂APIエラー (code={error.code})")


def hash_password(password: str) -> str:
    """パスワードをログインRPCで要求される形式にハッシュ化する。"""
    return hmac.new(_PASSWORD_HMAC_KEY, password.encode("utf-8"), hashlib.sha256).hexdigest()


def new_device_info() -> "pb.ClientDeviceInfo":
    """実機キャプチャで確認したブラウザ(Windows/Chrome)のdevice情報を再現する。"""
    device = pb.ClientDeviceInfo()
    device.platform = "pc"
    device.hardware = "pc"
    device.os = "windows"
    device.os_version = "win10"
    device.is_browser = True
    device.software = "Chrome"
    device.sale_platform = "web"
    device.screen_width = 1920
    device.screen_height = 1080
    device.screen_type = 1
    device.user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
    )
    return device


class MajsoulClient:
    """雀魂とのWebSocket RPC接続(1コネクション分)を管理する低レベルクライアント。"""

    def __init__(self, server: str = "jp") -> None:
        if server not in _SERVER_HOSTS:
            raise ValueError(f"未対応のサーバーです: {server!r} (対応: {list(_SERVER_HOSTS)})")
        self.server = server
        self.host = _SERVER_HOSTS[server]
        self.version = _FALLBACK_CLIENT_VERSION.get(server, "0.0.0.0")
        self._ws: Any = None
        self._dispatcher: asyncio.Task | None = None
        self._req_events: dict[int, asyncio.Event] = {}
        self._res: dict[int, bytes] = {}
        self._next_idx = 1

    async def __aenter__(self) -> "MajsoulClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def connect(self) -> None:
        last_error: Exception | None = None
        for endpoint in await self._candidate_gateways():
            try:
                # システムのHTTPプロキシ設定(mitmproxy調査時などに設定される場合がある)を
                # 無視し、常に直接接続する。
                self._ws = await websockets.connect(endpoint, origin=self.host, proxy=None)
                self._dispatcher = asyncio.create_task(self._dispatch())
                await self._request_connection()
                return
            except Exception as exc:  # noqa: BLE001 - 複数候補を順に試すため
                last_error = exc
        raise RuntimeError(f"ゲートウェイへの接続に失敗しました: {last_error}") from last_error

    async def _request_connection(self) -> None:
        """接続直後にRoute.requestConnectionを送る前段の握手。

        実機キャプチャで、ログイン関連のRPC(oauth2Auth等)より前に必ずこの呼び出しが
        行われていることを確認した。省略するとログインが失敗する(エラーcode=151)。
        """
        req = pb.ReqRequestConnection()
        req.type = 1
        req.route_id = _ROUTE_ID.get(self.server, f"{self.server}-1")
        req.timestamp = int(time.time())
        res = await self.call("requestConnection", req, service="Route")
        if res.error.code:
            raise MajsoulApiError(res.error)

    async def _candidate_gateways(self) -> list[str]:
        known = _KNOWN_GATEWAYS.get(self.server)
        if known:
            return [f"wss://{host}:443/gateway" for host in known]
        return [await self._discover_gateway()]

    async def close(self) -> None:
        if self._dispatcher:
            self._dispatcher.cancel()
            try:
                await self._dispatcher
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()

    async def _discover_gateway(self) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.host}/1/version.json") as res:
                version_info = await res.json(content_type=None)
                self.version = str(version_info["version"]).replace(".w", "")

            async with session.get(f"{self.host}/1/v{self.version}/config.json") as res:
                config = await res.json(content_type=None)
                region_urls = config["ip"][0]["region_urls"]
                url = next((r["url"] for r in region_urls if r.get("url")), None)
                if url is None:
                    raise RuntimeError("サーバー一覧の取得先URLが config.json から見つかりませんでした")

            async with session.get(f"{url}?service=ws-gateway&protocol=ws&ssl=true") as res:
                servers = (await res.json(content_type=None))["servers"]

        if not servers:
            raise RuntimeError("接続可能なゲートウェイサーバーが見つかりませんでした")
        server = random.choice(servers)
        return f"wss://{server}/gateway"

    async def _dispatch(self) -> None:
        assert self._ws is not None
        async for msg in self._ws:
            if isinstance(msg, str) or len(msg) < 3:
                continue
            type_byte = msg[0]
            if type_byte == 3:  # RESPONSE
                idx = int.from_bytes(msg[1:3], "little")
                self._res[idx] = msg
                event = self._req_events.get(idx)
                if event is not None:
                    event.set()
            # NOTIFY(1) / REQUEST(2) はこのツールの用途(牌譜取得)では使わないため無視

    async def call(self, method: str, request_message: Any, service: str = "Lobby") -> Any:
        """指定サービス(Lobby/Route)のメソッドを呼び出し、対応するレスポンスメッセージを返す。"""
        if self._ws is None:
            raise RuntimeError("connect() を先に呼び出してください")
        key = f"{service}.{method}"
        if key not in _RESPONSE_TYPES:
            raise ValueError(f"未対応のメソッドです: {key!r}")

        idx = self._next_idx
        self._next_idx = (self._next_idx + 1) % 60007

        name = f".lq.{service}.{method}"
        wrapper = pb.Wrapper(name=name, data=request_message.SerializeToString())
        packet = b"\x02" + idx.to_bytes(2, "little") + wrapper.SerializeToString()

        event = asyncio.Event()
        self._req_events[idx] = event
        await self._ws.send(packet)
        await asyncio.wait_for(event.wait(), timeout=30)

        raw = self._res.pop(idx)
        del self._req_events[idx]

        res_wrapper = pb.Wrapper()
        res_wrapper.ParseFromString(raw[3:])

        response = _RESPONSE_TYPES[key]()
        response.ParseFromString(res_wrapper.data)
        return response


async def login_with_email(client: MajsoulClient, email: str, password: str) -> "pb.ResLogin":
    """メールアドレス+パスワードでログインする(主経路)。"""
    req = pb.ReqEmailLogin()
    req.email = email
    req.password = hash_password(password)
    req.device.CopyFrom(new_device_info())
    req.random_key = str(uuid.uuid1())
    req.client_version = f"web-{client.version}"
    req.gen_access_token = True
    req.currency_platforms.append(2)

    res = await client.call("emailLogin", req)
    if res.error.code:
        raise MajsoulApiError(res.error)
    return res


async def login_with_yostar(
    client: MajsoulClient, yostar_token: str, yostar_uid: str, device_id: str
) -> "pb.ResLogin":
    """日本(Yostar)アカウントでログインする(oauth2Auth -> oauth2Check -> oauth2Loginの3段階)。

    :param yostar_token: ブラウザのLocal Storage(game.mahjongsoul.com)の "yostar_token" キーの値
    :param yostar_uid: 同じく "yostar_uid" キーの値
    :param device_id: 同じく "device_id" キーの値。oauth2Loginのrandom_keyに使う必要があった
        (実機キャプチャで、ブラウザは毎回のランダム値ではなくdevice_idそのものを送っていた)。
    """
    version_string = _CLIENT_VERSION_STRING.get(client.server, f"web-{client.version}")

    auth_req = pb.ReqOauth2Auth()
    auth_req.type = _YOSTAR_TYPE
    auth_req.code = yostar_token
    auth_req.uid = yostar_uid
    auth_req.client_version_string = version_string
    auth_res = await client.call("oauth2Auth", auth_req)
    if auth_res.error.code:
        raise MajsoulApiError(auth_res.error)
    fresh_token = auth_res.access_token

    check_req = pb.ReqOauth2Check()
    check_req.type = _YOSTAR_TYPE
    check_req.access_token = fresh_token
    check_res = await client.call("oauth2Check", check_req)
    if check_res.error.code:
        raise MajsoulApiError(check_res.error)

    login_req = pb.ReqOauth2Login()
    login_req.type = _YOSTAR_TYPE
    login_req.access_token = fresh_token
    login_req.device.CopyFrom(new_device_info())
    login_req.random_key = device_id
    login_req.client_version.resource = _CLIENT_VERSION_RESOURCE.get(client.server, client.version)
    login_req.client_version.package = _FALLBACK_CLIENT_VERSION.get(client.server, client.version)
    login_req.gen_access_token = True
    login_req.currency_platforms.extend([1, 3, 5, 9, 12])
    login_req.client_version_string = version_string
    login_req.tag = client.server

    res = await client.call("oauth2Login", login_req)
    if res.error.code:
        raise MajsoulApiError(res.error)
    return res

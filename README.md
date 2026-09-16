# mahjong-analyzer

雀魂(MahjongSoul)の牌譜を取得・解析し、統計と打牌ミスを可視化する個人用CLIツール。

## 現在の状態(2026年9月14日時点)

- **`parse` / `stats` / `mistakes` は動作確認済み**。`tests/fixtures/raw_game_basic.json` 相当のJSON(`fetch`が保存するのと同じ形式)を`data/raw/`に置けば、すぐに解析・統計・ミス検出を試せる。
- **ログイン(`login_with_yostar`)は解決済み**。mitmproxyで実際のブラウザのログイン通信をキャプチャし、バイト単位で比較することで正しいリクエスト形式(`oauth2Auth`→`oauth2Check`→`oauth2Login`の3段階、`type=21`、`Route.requestConnection`の事前ハンドシェイクが必須、等)を特定した。`.env`に`MAJSOUL_YOSTAR_TOKEN`/`MAJSOUL_YOSTAR_UID`/`MAJSOUL_DEVICE_ID`(ブラウザのLocal Storageから取得)を設定すれば動くはず。直接のoauth2Loginのみを叩く経路はCloudflareのTLSフィンガープリントで弾かれたが、requestConnectionハンドシェイクを含む完全なフローでは未再検証(次回セッションでまず`fetch`を試すこと)。
- **新たな壁: 牌譜データの形式(`actions`形式)が未対応**。`fetchGameRecord`が返す`GameDetailRecords`には、対応済みの`records`形式(`RecordDiscardTile`等)と、未対応の`actions`形式(`GameAction.user_input`/`user_event`/`result`)の2種類がある。**実際に試した牌譜は全て(2022年の古いものも含め)`actions`形式だった**ため、現状これを解かないと1件も解析できない。中身を調査するための詳細ダンプ機能は`capture/record_capture_addon.py`に実装済み(`data/raw_actions_diagnostic/`に出力)。次回は牌譜を1つ開いて、このダンプの中身(`user_input`/`user_event`に何が入っているか)を確認するところから再開すること。
- **ログインなしでのデータ取得手段が別途確立済み**: `capture/record_capture_addon.py`というmitmproxyアドオンが、ユーザー自身の(既にログイン済みの)ブラウザの通信を横取りして、`fetchGameRecord`のレスポンスをリアルタイムで`data/raw/`に保存する。使い方は「セットアップ」節を参照。上記の`actions`形式問題が解決すれば、この経路(またはfetch自動ログイン)でデータ収集を進められる。

## 注意事項(重要)

- 雀魂の牌譜取得には非公式のWebSocket/Protobuf APIを使用します。利用規約上グレーゾーン〜違反となる可能性があり、**アカウントBANのリスクを理解した上で自己責任で使用してください**。
- 本ツールは**自分のプレイ履歴を事後的に振り返り・分析する**ことのみを目的としています。対局中にリアルタイムで指し手の助言を受ける用途(いわゆる不正ツール)には使用しないでください。
- ログイン方式はゲーム側の仕様変更で壊れる可能性があります。動作しなくなった場合はプロトコル定義(`mahjong_analyzer/fetcher/proto/`)の更新が必要です。

## セットアップ

```bash
pip install -e ".[dev]"
cp .env.example .env
# .env に MAJSOUL_YOSTAR_TOKEN / MAJSOUL_YOSTAR_UID / MAJSOUL_DEVICE_ID を設定
# (ブラウザで game.mahjongsoul.com にログイン → F12 → Application → Local Storage から取得)
```

### 代替手段: ブラウザ経由でのキャプチャ(mitmproxy)

`fetch`の自動ログインが使えない/信用できない場合、自分のブラウザの通信を横取りしてデータを取る方法もある。

```bash
pip install mitmproxy
mitmdump -s capture/record_capture_addon.py --listen-port 8080
```

1. Windowsのプロキシ設定(設定→ネットワークとインターネット→プロキシ)を手動で`127.0.0.1:8080`にする
2. ブラウザで`http://mitm.it`を開き証明書をインストール・信頼する
3. `https://game.mahjongsoul.com/`でログインし、牌譜画面から見たい対局の「詳細」を1つずつ開く
4. 開くたびに`data/raw/{uuid}.json`が自動保存される

作業が終わったらWindowsのプロキシ設定は必ずオフに戻すこと(オンのままだと他の通信もできなくなる)。

## 使い方

```bash
# 直近5局の牌譜を取得してdata/raw/に保存(現状、自動ログインが未解決のため失敗する場合あり。上記「現在の状態」参照)
python -m mahjong_analyzer fetch --recent 5

# 取得済みrawデータを正規化イベント列に変換
python -m mahjong_analyzer parse

# 統計(和了率・放銃率・平均順位など)を表示
python -m mahjong_analyzer stats

# 打牌ミス(シャンテン/受け入れ枚数が劣る選択)を一覧表示
python -m mahjong_analyzer mistakes
```

`fetch`が使えない間でも、`fetch`が生成するのと同じ形式のJSONファイルを`data/raw/`に置けば`parse`以降は動作する。期待される形式は [tests/fixtures/raw_game_basic.json](tests/fixtures/raw_game_basic.json) を参照(`uuid` / `head.accounts` / `head.result.players` / `records[].name`+`data` を持つ構造)。

## テスト

```bash
pytest
```

ネットワーク接続や雀魂アカウントなしで動かせるよう、`tests/fixtures/` にサンプル牌譜(mjai風JSON)を用意しています。

## 今後の拡張予定

- Web UIでの牌譜可視化・リプレイ
- [Mortal](https://mortal.ekyu.moe/) / [mjai-reviewer](https://github.com/Equim-chan/mjai-reviewer) を外部プロセスとして呼び出すAI比較機能(Mortal自体はAGPLライセンスのため本リポジトリには組み込まない)

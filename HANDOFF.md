# HANDOFF.md — mahjong-analyzer 引き継ぎメモ

PC移行用のまとめ。詳細な経緯は `.claude/plans/` のプラン、およびClaude側のプロジェクトメモリを参照。

## このアプリが何をするものか

雀魂(MahjongSoul)の牌譜(対局ログ)を取得・解析する**自分専用**のツール。
- 牌効率(シャンテン数・受け入れ枚数)の観点での打牌ミス検出
- 強豪AI「Mortal」との比較によるEVベースの評価(押し引き・鳴き判断・リーチ判断など)
- 連戦時の調子の波(コンディション傾向)分析
- 上記をまとめて見るWebダッシュボード(FastAPI + Jinja2)

CLIとWeb UIの二本立てで、CLIが牌譜取得〜解析〜DB保存を行い、Web UIはDBと解析結果を閲覧するだけの構成。

## 実装済み機能

- 雀魂からの牌譜取得(CLI `fetch`。Yostarログイン)
- mitmproxyベースの一括取得アドオン(`capture/record_capture_addon.py`)で、自分の全対局履歴を自動巡回取得可能(実アカウントで1279局を確認済み。現在33局のみDB取り込み済み)
- 牌譜パース(`parse`): 雀魂の生データ→正規化イベント列(mjai風)
- 統計集計(`stats`): 和了率・放銃率・平均順位・リーチ率・副露率
- 牌効率ミス検出(`mistakes`): シャンテン数・受け入れ枚数ベース
  - ミスを重症度別に3分類(シャンテン後退/受け入れの大きな見落とし/わずかな見落とし)
  - 打点(ドラ枚数)を優先した結果として妥当なシャンテン後退は「ミス」から除外
  - 他家リーチ後の防御中に生じたシャンテン低下も「ミス」から除外(攻めている場面のみを牌効率の評価対象にする設計)
- Mortal AI連携の**アーキテクチャ**(`review/`)。mjaiプロトコル(JSON Lines)でMortalプロセスを呼び出す設計・EV差分からのミス判定ロジックまでは実装・テスト済みだが、**Mortal本体を実際に動かしたことは一度もない**(下記「未完了タスク」参照)
- 評価軸(`review`→`score`): 押し引き・鳴き判断・リーチ判断・着順/点数状況判断・手役打点構築判断・降り技術の質(いずれもMortal実行が前提、現状「レビュー未実行」表示)
- コンディション傾向分析: セッション内の対局順・直前局の着順・時間帯別のミス率(Mortal不要、実データで動作確認済み)
- 牌譜フィルター(直近N戦 / 期間指定)
- Web UI: トップページ(ユーザーネーム or IDで検索、ワンクリックで自分のダッシュボードへ)、ダッシュボード(評価軸カード+クリックでドリルダウン、対局概要、ミス種別内訳、コンディション傾向グラフ)
- テスト96件(pytest、すべてMortal非依存で実行可能)

## 未完了タスク・既知の問題

- **最大の未検証ポイント**: Mortal本体(強豪AI)を一度も実行していない。ビルド(Rustツールチェーン/maturin、またはDocker)が未実施。旧PCはRAM 3.8GBの制約でリスクと判断し保留していた。mjaiプロトコルの細かいフィールド仕様(`review/mortal_client.py`の`_extract_q_values()`等)も未検証で、実際に動かすと調整が必要になる可能性が高い
- 残り約1240局(全1279局中33局のみ取得済み)の一括取得が未完了。手順は確立済み(`capture/record_capture_addon.py`をmitmdumpで起動し、ブラウザでログイン)
- 鳴き判断・リーチ判断の「見逃し」検出(スルーした/リーチしなかった判断の評価)は未対応。牌譜には実際に取った行動しか残らないため、Mortalの実出力を見て設計する必要がある
- 点数状況に応じた打牌の妥当性判断(例: オーラス首位での孤立役牌問題)は、信頼できるルール情報源が見つからず保留。将来的にMortal(または複数AI比較)の実データで判定する方針
- 複数AI合議(Naga/MAKA/LuckyJ)は調査済みで不採用。いずれもプログラムからの自動アクセスができない(NAGAは有料Webサービス、MAKAは雀魂内蔵機能で1日10〜30回制限、LuckyJは非公開)。Mortal単体をground truthとする方針
- 将来的な複数ユーザー対応(ホスト型サービス化)は未着手。参考にamae-koromoの仕組みを調査済みだが、常時稼働のBotアカウントが必要になりリスクが上がるため、Mortal検証後に改めて設計する方針

## ローカルでの起動手順

```bash
# 1. 仮想環境を作成して依存関係をインストール
python -m venv .venv
source .venv/Scripts/activate   # Windows
pip install -e ".[dev]"

# 2. .env を用意(.env.example をコピーして値を設定。下記「別途用意が必要なもの」参照)

# 3. データ取得・解析(牌譜が無い場合)
python -m mahjong_analyzer.cli fetch --recent 5   # または capture/ のmitmproxyアドオンで一括取得
python -m mahjong_analyzer.cli parse
python -m mahjong_analyzer.cli mistakes

# 4. Web UIを起動
python -m mahjong_analyzer.cli serve --port 8000
# http://127.0.0.1:8000/ を開く
```

主なCLIサブコマンド: `fetch` / `parse` / `stats` / `mistakes` / `review`(Mortal実行、未検証) / `score` / `serve`

## 技術スタック

- Python 3.10+ (3.14.6で動作確認)
- 雀魂通信: `websockets` + `protobuf`(非公式WebSocket API、`liqi.proto`)
- CLI: `typer` + `rich`
- Web: `fastapi` + `jinja2` + `uvicorn`(`[standard]`不使用、素のASGIのみ)
- フロントエンド: 素のHTML/CSS/JS + Chart.js(CDN経由)、ビルドステップなし
- 牌効率計算: `mahjong`パッケージ(MahjongRepository, MIT)
- DB: SQLite(`data/mahjong_analyzer.db`)
- テスト: `pytest`
- Mortal AI: 外部プロセスとして呼び出す設計(AGPL-3.0のためコードはリンクしない)、mjaiプロトコル(JSON Lines)でやり取り

## 主要フォルダ・ファイル

```
mahjong_analyzer/
  config.py              .envの読み込み、Settings
  cli.py                 CLIエントリポイント
  data_access.py         解析済み牌譜(data/parsed/)の読み込み
  filters.py              牌譜フィルター(直近N戦・期間指定)
  tiles.py                牌表記変換・ドラ判定
  fetcher/                雀魂への接続・ログイン・牌譜ダウンロード
  parser/                 生データ→正規化イベント列(mjai風)への変換
  analysis/
    efficiency.py         牌効率ミス検出・重症度分類・ドラ正当化判定
    stats.py               統計集計
    report.py               全評価軸を集約するScoreReport構築(CLI/Web共通)
    scoring.py               偏差値・スコア計算
    axes/                    評価軸ごとのロジック(push_fold/naki/riichi/
                             rank_strategy/hand_value/defense_quality/
                             condition/condition_insights/context/base)
  review/                  Mortal AI連携(mjai_export.py, mortal_client.py)。未実行
  storage/db.py            SQLiteスキーマ・読み書き
  web/                     FastAPI Webアプリ(app.py, view_model.py, templates/)

capture/                  mitmproxyの一括取得アドオン(record_capture_addon.py)
tests/                    pytestテスト(96件)
data/                     [gitignore] raw/parsed牌譜JSON・SQLite DB
mortal/                   [gitignore] Mortalモデル・config.toml配置場所
```

## 新PCで別途用意・設定が必要なもの

`.gitignore`で除外しているため、GitHubからcloneしただけでは以下が欠けている:

1. **Python仮想環境**: `python -m venv .venv` → `pip install -e ".[dev]"`(別マシンの`.venv`はコピーしても動かない)
2. **`.env`ファイル**(`.env.example`をコピーして値を設定。値は本メモには記載しない):
   - `MAJSOUL_SERVER`
   - `MAJSOUL_YOSTAR_TOKEN`
   - `MAJSOUL_YOSTAR_UID`
   - `MAJSOUL_DEVICE_ID`
   - `MAJSOUL_EMAIL` / `MAJSOUL_PASSWORD`(CN版アカウント向け、通常未使用)
   - `MAHJONG_ANALYZER_DATA_DIR`
   - `MY_ACCOUNT_ID`
   - `MORTAL_BINARY_PATH`
   - `MORTAL_MODEL_PATH`
3. **`data/`ディレクトリの中身**(牌譜JSON・SQLite DB): gitに含まれないため、旧PCから直接コピーするか、`fetch`からやり直す
4. **Mortalモデルファイル**(`mortal/model/mortal_298k.pth`、約131MB): HuggingFace `VoidShine/mortal-298k` から再ダウンロードが必要(URLは既知、Mortal本体は未ビルド)
5. **Rust/maturinツールチェーン**(Mortal本体を実際にビルド・実行する場合。現状未着手)

## 開発を続ける際の注意点

- `.venv`はマシン間で移動できない(絶対パス依存)。ファイル同期(OneDrive等)する場合は必ず除外すること。`.venv`はファイル数が非常に多く(数千個)、同期を極端に遅くする原因にもなる
- `mistakes`コマンドのシャンテン計算は重い(33局で数分〜十数分)。結果はDBにキャッシュされ、`report.py`等はDBから読む設計になっている(再計算を避けるため)。`mistakes`テーブルのスキーマを変更した場合は、既存DBの該当カラムがデフォルト値のままになるので`mistakes`コマンドの再実行(バックフィル)が必要
- Web UIのPythonコード(`web/`, `analysis/`等)を変更した場合、`serve`コマンド(uvicorn)の再起動が必要
- Mortalの実行方式(ネイティブビルド or Docker)は、新PCのスペック次第で再検討すること。旧PCはRAM 3.8GBの制約でネイティブビルドを優先する判断をしていたが、新PCのスペックが十分ならDockerの方が簡単な可能性がある
- `.env`・`data/`・`capture/*.flow`(mitmproxyの生通信キャプチャ、認証トークンを含む)は個人情報・認証情報を含むため、**絶対にgitにコミットしない**こと(`.gitignore`済みだが、新規ファイルを追加する際は要注意)
- 複数AI合議(Naga/MAKA/LuckyJ)は調査済みで不採用と結論済み。再検討する場合は「プログラムアクセス不可」という結論を覆す新情報が必要
- 現状は「自分専用ツール」という前提のUI(`account_id`が`.env`の`MY_ACCOUNT_ID`と一致する場合のみ閲覧可)。複数ユーザー対応の設計は保留中(amae-koromo方式を参考に検討していたが、常時稼働Botアカウントが必要になりBANリスクが上がるため未着手)

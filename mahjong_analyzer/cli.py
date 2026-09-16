"""mahjong-analyzer CLIエントリポイント。"""

from __future__ import annotations

import asyncio
import json
from datetime import date

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from mahjong_analyzer.analysis.axes.context import enrich_with_context
from mahjong_analyzer.analysis.efficiency import find_mistakes
from mahjong_analyzer.analysis.report import build_score_report, my_seat
from mahjong_analyzer.analysis.scoring import to_deviation_values
from mahjong_analyzer.analysis.stats import aggregate_stats
from mahjong_analyzer.config import Settings, load_settings
from mahjong_analyzer.data_access import load_parsed_games
from mahjong_analyzer.fetcher.client import MajsoulClient, login_with_email, login_with_yostar
from mahjong_analyzer.fetcher.downloader import download_game_record, list_recent_games, save_raw_record
from mahjong_analyzer.filters import GameFilter, apply_filter
from mahjong_analyzer.parser.majsoul_to_mjai import convert
from mahjong_analyzer.review.mortal_client import MortalNotAvailableError, NativeMortalEngine, review_game
from mahjong_analyzer.storage import db

app = typer.Typer(help="雀魂(MahjongSoul)牌譜の取得・解析・統計・打牌ミス検出ツール")
console = Console()


async def _login(settings: Settings, client: MajsoulClient) -> None:
    has_yostar = settings.majsoul_yostar_token and settings.majsoul_yostar_uid and settings.majsoul_device_id
    if has_yostar:
        console.print("Yostarアカウントでログインしています...")
        await login_with_yostar(
            client,
            settings.majsoul_yostar_token,
            settings.majsoul_yostar_uid,
            settings.majsoul_device_id,
        )
        console.print("[green]ログイン成功 (oauth2Auth -> oauth2Login)[/green]")
        return

    if settings.majsoul_email and settings.majsoul_password:
        console.print("メールアドレス+パスワードでログインしています...")
        await login_with_email(client, settings.majsoul_email, settings.majsoul_password)
        console.print("[green]ログイン成功 (emailLogin)[/green]")
        return

    raise RuntimeError(
        "ログイン情報がありません。.env に MAJSOUL_YOSTAR_TOKEN/MAJSOUL_YOSTAR_UID/"
        "MAJSOUL_DEVICE_ID(日本版アカウント向け)、または MAJSOUL_EMAIL/MAJSOUL_PASSWORD"
        "(CN版アカウント向け)を設定してください。"
    )


async def _fetch_async(settings: Settings, recent: int, paipu_id: str | None) -> None:
    async with MajsoulClient(settings.majsoul_server) as client:
        await _login(settings, client)

        if paipu_id:
            uuids = [paipu_id]
        else:
            console.print(f"直近{recent}件の対局一覧を取得しています...")
            games = await list_recent_games(client, count=recent)
            uuids = [g["uuid"] for g in games]
            console.print(f"{len(uuids)}件見つかりました")

        with db.open_db(settings.db_path) as conn:
            for uuid in uuids:
                console.print(f"取得中: {uuid}")
                record = await download_game_record(client, uuid)
                path = save_raw_record(record, settings.raw_dir)
                db.record_fetched_game(conn, uuid, str(path))
                console.print(f"  -> 保存: {path}")


@app.command()
def fetch(
    recent: int = typer.Option(5, help="取得する直近対局数(--paipu-id指定時は無視)"),
    paipu_id: str | None = typer.Option(None, "--paipu-id", help="特定の牌譜IDを1件だけ取得する"),
) -> None:
    """雀魂から牌譜を取得し data/raw/ にJSONとして保存する。"""
    settings = load_settings()
    asyncio.run(_fetch_async(settings, recent, paipu_id))


@app.command(name="parse")
def parse_command() -> None:
    """data/raw/ の牌譜を正規化イベント列に変換し、data/parsed/ とDBに保存する。"""
    settings = load_settings()
    raw_files = sorted(settings.raw_dir.glob("*.json"))
    if not raw_files:
        console.print("[yellow]data/raw/ に牌譜が見つかりません。先に fetch を実行してください。[/yellow]")
        raise typer.Exit(code=1)

    with db.open_db(settings.db_path) as conn:
        for raw_path in raw_files:
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            game_log = convert(raw)
            out_path = settings.parsed_dir / f"{game_log.paipu_id}.json"
            out_path.write_text(
                json.dumps(game_log.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
            db.record_parsed_game(conn, game_log)
            console.print(f"変換完了: {raw_path.name} -> {out_path.name}")


@app.command(name="stats")
def stats_command() -> None:
    """複数対局の統計(和了率・放銃率・平均順位など)を表示する。"""
    settings = load_settings()
    game_logs = load_parsed_games(settings)
    if not game_logs:
        console.print("[yellow]解析済みの牌譜が見つかりません。先に parse を実行してください。[/yellow]")
        raise typer.Exit(code=1)

    player_stats = aggregate_stats(game_logs)

    table = Table(title="成績統計")
    for col in ["プレイヤー", "半荘数", "平均順位", "和了率", "放銃率", "リーチ率", "副露率", "平均和了点", "平均放銃点"]:
        table.add_column(col)
    for s in sorted(player_stats.values(), key=lambda s: s.avg_rank or 99):
        table.add_row(
            s.name,
            str(s.games),
            f"{s.avg_rank:.2f}",
            f"{s.win_rate:.1%}",
            f"{s.deal_in_rate:.1%}",
            f"{s.riichi_rate:.1%}",
            f"{s.call_rate:.1%}",
            f"{s.avg_win_score:.0f}",
            f"{s.avg_deal_in_score:.0f}",
        )
    console.print(table)

    with db.open_db(settings.db_path) as conn:
        db.record_player_stats(conn, player_stats)


@app.command(name="mistakes")
def mistakes_command(
    paipu_id: str | None = typer.Option(None, "--paipu-id", help="特定の牌譜IDのみ表示する"),
) -> None:
    """打牌ミス(牌効率の観点でのシャンテン/受け入れ枚数の損失)を一覧表示する。"""
    settings = load_settings()
    game_logs = load_parsed_games(settings)
    if paipu_id:
        game_logs = [g for g in game_logs if g.paipu_id == paipu_id]
    if not game_logs:
        console.print("[yellow]解析済みの牌譜が見つかりません。先に parse を実行してください。[/yellow]")
        raise typer.Exit(code=1)

    with db.open_db(settings.db_path) as conn:
        for game_log in game_logs:
            game_mistakes = find_mistakes(game_log)
            db.record_mistakes(conn, game_log.paipu_id, game_mistakes)

            if not game_mistakes:
                console.print(f"[green]ミスなし: {game_log.paipu_id}[/green]")
                continue

            table = Table(title=f"打牌ミス: {game_log.paipu_id}")
            for col in ["局", "巡目", "プレイヤー", "実際の打牌", "最善打", "シャンテン(実際/最善)", "受け入れ差"]:
                table.add_column(col)
            for m in game_mistakes:
                table.add_row(
                    str(m.kyoku_index + 1),
                    str(m.turn),
                    game_log.player_name(m.actor),
                    m.discarded,
                    m.best_discard,
                    f"{m.shanten_after_actual}/{m.shanten_after_best}",
                    str(m.ukeire_loss),
                )
            console.print(table)


@app.command(name="review")
def review_command(
    paipu_id: str | None = typer.Option(None, "--paipu-id", help="特定の牌譜IDのみレビューする"),
    all_seats: bool = typer.Option(False, "--all-seats", help="自分だけでなく4人全員をレビューする"),
) -> None:
    """牌譜をMortal AIでレビューし、EVロスをDBに保存する(押し引き/鳴き/リーチ等の軸で使う)。"""
    settings = load_settings()
    engine = NativeMortalEngine(settings.mortal_binary_path, settings.mortal_model_path)

    game_logs = load_parsed_games(settings)
    if paipu_id:
        game_logs = [g for g in game_logs if g.paipu_id == paipu_id]
    if not game_logs:
        console.print("[yellow]解析済みの牌譜が見つかりません。先に parse を実行してください。[/yellow]")
        raise typer.Exit(code=1)

    with db.open_db(settings.db_path) as conn:
        for game_log in game_logs:
            if all_seats:
                seats = [0, 1, 2, 3]
            else:
                seat = my_seat(settings, game_log)
                if seat is None:
                    console.print(
                        f"[yellow]スキップ: {game_log.paipu_id} (MY_ACCOUNT_ID未設定、または自分が参加していない対局)[/yellow]"
                    )
                    continue
                seats = [seat]

            try:
                decisions = review_game(game_log, engine, seats=seats)
            except MortalNotAvailableError as e:
                console.print(f"[red]{e}[/red]")
                raise typer.Exit(code=1) from e

            decisions = enrich_with_context(game_log, decisions)
            db.record_mortal_decisions(conn, game_log.paipu_id, decisions)
            console.print(f"レビュー完了: {game_log.paipu_id} ({len(decisions)}件の判断ポイント)")


def _check_score_prerequisites(settings: Settings) -> list:
    if settings.my_account_id is None:
        console.print("[red]MY_ACCOUNT_ID が.envに設定されていません。[/red]")
        raise typer.Exit(code=1)
    game_logs = load_parsed_games(settings)
    if not game_logs:
        console.print("[yellow]解析済みの牌譜が見つかりません。先に parse を実行してください。[/yellow]")
        raise typer.Exit(code=1)
    return game_logs


@app.command(name="score")
def score_command(
    recent: int | None = typer.Option(None, "--recent", help="直近N戦のみを対象にする"),
    date_from: str | None = typer.Option(None, "--from", help="この日付(YYYY-MM-DD)以降を対象にする"),
    date_to: str | None = typer.Option(None, "--to", help="この日付(YYYY-MM-DD)以前を対象にする"),
) -> None:
    """各評価軸(牌効率/押し引き/鳴き/リーチ/着順戦略/打点構築/降り技術/コンディション)を表示する。"""
    settings = load_settings()
    all_game_logs = _check_score_prerequisites(settings)
    game_filter = GameFilter(
        recent=recent,
        date_from=date.fromisoformat(date_from) if date_from else None,
        date_to=date.fromisoformat(date_to) if date_to else None,
    )
    game_logs = apply_filter(all_game_logs, game_filter)
    if not game_logs:
        console.print("[yellow]指定した条件に一致する牌譜がありません。[/yellow]")
        raise typer.Exit(code=1)
    if game_filter.is_active:
        console.print(f"[dim]{len(game_logs)} / {len(all_game_logs)} 半荘を対象に集計します[/dim]")
    report = build_score_report(settings, game_logs=game_logs)

    console.print("[bold]牌効率(既存のmistakesベース、Mortal不要)[/bold]")
    console.print(f"  ミス件数合計: {report.total_mistakes} ({report.games_count}半荘)")
    if report.excluded_defending_count or report.excluded_dora_justified_count:
        console.print(
            f"  [dim]除外(ミスとして数えていません): 防御中のシャンテン低下 "
            f"{report.excluded_defending_count}件 ・ 打点(ドラ)重視の妥当な選択 "
            f"{report.excluded_dora_justified_count}件[/dim]"
        )

    if not report.has_mortal_data:
        console.print(
            "\n[yellow]Mortalレビュー結果がまだありません。`review` コマンドを実行してください"
            "(Mortalのセットアップが未完了の場合はエラーメッセージが出ます)。[/yellow]"
        )
    else:
        console.print("\n[bold]Mortal比較ベースの評価軸[/bold]")
        for score in (report.push_fold, report.naki, report.riichi):
            console.print(
                f"  {score.name}: n={score.sample_size} 平均EVロス={score.avg_ev_loss:.3f} "
                f"ミス率={score.mistake_rate:.1%}"
            )

        rank_report = report.rank_strategy
        console.print(
            f"  {rank_report.overall.name}: n={rank_report.overall.sample_size} "
            f"平均EVロス={rank_report.overall.avg_ev_loss:.3f}"
        )
        for rank, s in sorted(rank_report.by_rank.items()):
            console.print(f"    {s.name}: n={s.sample_size} 平均EVロス={s.avg_ev_loss:.3f}")
        console.print(
            f"    {rank_report.all_last.name}: n={rank_report.all_last.sample_size} "
            f"平均EVロス={rank_report.all_last.avg_ev_loss:.3f}"
        )

        hv = report.hand_value
        console.print(
            f"  手役・打点構築判断: 牌効率ミス{hv.efficiency_mistakes}件中、"
            f"打点重視の妥当な選択={hv.value_favoring}件 純粋な失着={hv.pure_mistakes}件 "
            f"(妥当率={hv.value_favoring_rate:.1%})"
        )

        dq = report.defense_quality
        if dq.defending_decisions:
            console.print(
                f"  降り技術の質: 危険な状況での打牌{dq.defending_decisions}件中、"
                f"現物選択={dq.genbutsu_choices}件 ({dq.genbutsu_rate:.1%}) "
                f"現物以外の平均EVロス={dq.non_genbutsu_avg_ev_loss:.3f}"
            )

    console.print("\n[bold]メンタル/コンディション傾向(牌効率ミス率の時系列、Mortal不要)[/bold]")
    if not report.condition_timeline:
        console.print("  [yellow]対局開始時刻の情報がある牌譜がありません。[/yellow]")
    else:
        rates = [c.mistake_rate for c in report.condition_timeline]
        deviations = to_deviation_values(rates)
        table = Table(title="コンディション傾向")
        for col in ["対局", "セッション内何局目", "ミス率", "偏差値"]:
            table.add_column(col)
        for c, dv in zip(report.condition_timeline, deviations):
            table.add_row(c.paipu_id, str(c.games_into_session), f"{c.mistake_rate:.1%}", f"{dv:.1f}")
        console.print(table)


@app.command(name="serve")
def serve_command(port: int = typer.Option(8000, "--port", help="待ち受けポート")) -> None:
    """自分専用Web UIをローカルで起動する(127.0.0.1のみ、外部ネットワークには公開しない)。"""
    console.print(f"http://127.0.0.1:{port}/ で待ち受けます(Ctrl+Cで停止)")
    uvicorn.run("mahjong_analyzer.web.app:app", host="127.0.0.1", port=port)


if __name__ == "__main__":
    app()

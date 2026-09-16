"""自分専用Web UI(FastAPI)。

「ユーザーネーム/ID入力 → 結果出力」という将来の複数ユーザー対応を見据えた
画面構成にしつつ、機能的には自分専用(入力されたaccount_idが設定済みの
MY_ACCOUNT_IDと一致する場合のみダッシュボードを表示)というスコープに留める
(①のスコープ決定と整合)。

`cli.py`の`serve`コマンドから`127.0.0.1`のみにbindして起動する前提。個人用
ツールとして外部ネットワークに公開しないための既定の安全策。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from mahjong_analyzer.analysis.report import build_score_report
from mahjong_analyzer.analysis.scoring import to_deviation_values
from mahjong_analyzer.analysis.stats import aggregate_stats
from mahjong_analyzer.config import Settings, load_settings
from mahjong_analyzer.data_access import load_parsed_games
from mahjong_analyzer.filters import GameFilter, apply_filter
from mahjong_analyzer.storage import db
from mahjong_analyzer.web.view_model import (
    build_axis_cards,
    build_overall_card,
    mistake_category_breakdown,
    mistake_detail_rows,
)

_TEMPLATES_DIR = Path(__file__).parent / "templates"

app = FastAPI(title="mahjong-analyzer")
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _my_name(settings: Settings) -> str | None:
    if settings.my_account_id is None:
        return None
    game_logs = load_parsed_games(settings)
    return next(
        (p.name for gl in game_logs for p in gl.players if p.account_id == settings.my_account_id),
        None,
    )


def _resolve_account_id(settings: Settings, raw_input: str) -> int | None:
    """入力(ID または ユーザーネーム)からaccount_idを解決する。

    雀魂には「他人のIDで検索する」公開APIが無く自分専用ツールという前提なので、
    ここではsettings.my_account_id自身にしか解決しない(数字ならID一致、文字列なら
    その人が過去に名乗ったニックネームと一致するかで判定)。
    """
    raw_input = raw_input.strip()
    if not raw_input or settings.my_account_id is None:
        return None
    if raw_input.isdigit() and int(raw_input) == settings.my_account_id:
        return settings.my_account_id
    with db.open_db(settings.db_path) as conn:
        known_names = db.known_names_for_account(conn, settings.my_account_id)
    if raw_input in known_names:
        return settings.my_account_id
    return None


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    settings = load_settings()
    my_name = _my_name(settings)
    return templates.TemplateResponse(
        request,
        "index.html",
        {"quick_name": my_name, "quick_id": settings.my_account_id if my_name else None},
    )


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    account_id: str = "",
    recent: str = "",
    date_from: str = "",
    date_to: str = "",
) -> HTMLResponse:
    settings = load_settings()

    entered_id = _resolve_account_id(settings, account_id)
    if entered_id is None:
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "error": "IDまたはユーザーネームが確認できませんでした(現在は自分のIDのみ対応しています)。",
                "quick_name": _my_name(settings),
                "quick_id": settings.my_account_id,
            },
        )

    all_game_logs = load_parsed_games(settings)
    if not all_game_logs:
        return templates.TemplateResponse(
            request,
            "index.html",
            {"error": "解析済みの牌譜がありません。先に `parse` を実行してください。"},
        )

    my_name = next(
        (p.name for gl in all_game_logs for p in gl.players if p.account_id == settings.my_account_id),
        None,
    )

    game_filter = GameFilter(
        recent=int(recent) if recent.strip().isdigit() else None,
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
    )
    game_logs = apply_filter(all_game_logs, game_filter)

    player_stats = aggregate_stats(game_logs)
    my_stats = player_stats.get(my_name) if my_name else None

    report = build_score_report(settings, game_logs=game_logs)
    condition_deviations = to_deviation_values([c.mistake_rate for c in report.condition_timeline])
    condition_rows = [
        {"condition": c, "deviation": round(dv, 1)}
        for c, dv in zip(report.condition_timeline, condition_deviations)
    ]
    condition_chart = {
        "labels": [c.short_date_label for c in report.condition_timeline],
        "rates": [round(c.mistake_rate * 100, 1) for c in report.condition_timeline],
    }

    axis_cards = build_axis_cards(report)
    overall_card = build_overall_card(axis_cards)

    date_by_paipu = {c.paipu_id: c.date_label for c in report.condition_timeline}
    mistake_rows = mistake_detail_rows(report, date_by_paipu)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "account_id": entered_id,
            "my_name": my_name,
            "my_stats": my_stats,
            "report": report,
            "condition_rows": condition_rows,
            "condition_chart_json": json.dumps(condition_chart, ensure_ascii=False),
            "overall_card": overall_card,
            "axis_cards": axis_cards,
            "mistake_categories": mistake_category_breakdown(report),
            "mistake_rows": mistake_rows,
            "filter_recent": recent,
            "filter_date_from": date_from,
            "filter_date_to": date_to,
            "filter_active": game_filter.is_active,
            "total_games_available": len(all_game_logs),
        },
    )

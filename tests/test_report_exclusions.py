"""build_score_report が、防御中のシャンテン低下・打点重視の妥当な選択を
牌効率ミスから正しく除外することの結合テスト(DB+GameLogを実際に組み合わせる)。
"""

from __future__ import annotations

import json
from pathlib import Path

from mahjong_analyzer.analysis.efficiency import find_mistakes
from mahjong_analyzer.analysis.report import build_score_report
from mahjong_analyzer.config import Settings
from mahjong_analyzer.parser.model import GameLog, PlayerInfo
from mahjong_analyzer.storage import db

_PLAYERS = [
    PlayerInfo(0, "Me", account_id=42),
    PlayerInfo(1, "B"),
    PlayerInfo(2, "C"),
    PlayerInfo(3, "D"),
]

_HAND14 = ["1m", "2m", "3m", "4p", "5p", "6p", "7s", "8s", "9s", "S", "S", "3s", "5s", "E"]


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        majsoul_email=None,
        majsoul_password=None,
        majsoul_yostar_token=None,
        majsoul_yostar_uid=None,
        majsoul_device_id=None,
        majsoul_server="jp",
        data_dir=tmp_path,
        mortal_binary_path=tmp_path / "mortal",
        mortal_model_path=tmp_path / "model.pth",
        my_account_id=42,
    )


def _build_game_log() -> GameLog:
    events = [
        # 局1: 通常のミス(防御中でもドラ重視でもない、純粋な見落とし)
        {
            "type": "start_kyoku",
            "bakaze": "E",
            "kyoku": 1,
            "scores": [25000, 25000, 25000, 25000],
            "tehais": [_HAND14, ["?"] * 13, ["?"] * 13, ["?"] * 13],
            "dora_marker": "1s",  # ドラは2s、手牌には無関係
        },
        {"type": "dahai", "actor": 0, "pai": "S", "tsumogiri": False},
        {"type": "end_kyoku"},
        # 局2: ドラ(E)を残すシャンテン後退 -> 打点重視として除外されるべき
        {
            "type": "start_kyoku",
            "bakaze": "E",
            "kyoku": 2,
            "scores": [25000, 25000, 25000, 25000],
            "tehais": [_HAND14, ["?"] * 13, ["?"] * 13, ["?"] * 13],
            "dora_marker": "N",  # ドラはE
        },
        {"type": "dahai", "actor": 0, "pai": "S", "tsumogiri": False},
        {"type": "end_kyoku"},
        # 局3: 他家リーチ後(防御中)のシャンテン後退 -> 除外されるべき
        {
            "type": "start_kyoku",
            "bakaze": "E",
            "kyoku": 3,
            "scores": [25000, 25000, 25000, 25000],
            "tehais": [_HAND14, ["?"] * 13, ["?"] * 13, ["?"] * 13],
            "dora_marker": "1s",
        },
        {"type": "dahai", "actor": 1, "pai": "1p", "tsumogiri": False},
        {"type": "reach", "actor": 1},
        {"type": "dahai", "actor": 0, "pai": "S", "tsumogiri": False},
        {"type": "end_kyoku"},
    ]
    return GameLog(
        paipu_id="g1", players=_PLAYERS, events=events, start_time=1_700_000_000, end_time=1_700_001_000
    )


def test_defending_and_dora_justified_mistakes_are_excluded(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    game_log = _build_game_log()

    settings.parsed_dir.mkdir(parents=True, exist_ok=True)
    (settings.parsed_dir / f"{game_log.paipu_id}.json").write_text(
        json.dumps(game_log.to_dict(), ensure_ascii=False), encoding="utf-8"
    )

    raw_mistakes = find_mistakes(game_log)
    assert len(raw_mistakes) == 3  # 3局とも検出はされる(除外は集計時に行う)

    with db.open_db(settings.db_path) as conn:
        db.record_parsed_game(conn, game_log)  # mistakesテーブルのFK制約(games参照)を満たす
        db.record_mistakes(conn, game_log.paipu_id, raw_mistakes)

    report = build_score_report(settings, game_logs=[game_log])

    assert report.total_mistakes == 1  # 局1の純粋なミスだけが残る
    assert report.excluded_dora_justified_count == 1  # 局2
    assert report.excluded_defending_count == 1  # 局3
    assert report.mistakes_by_paipu["g1"][0].kyoku_index == 0

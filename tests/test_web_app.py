"""web.app のID/ユーザーネーム解決ロジックのテスト。"""

from __future__ import annotations

from pathlib import Path

from mahjong_analyzer.config import Settings
from mahjong_analyzer.parser.model import GameLog, PlayerInfo
from mahjong_analyzer.storage import db
from mahjong_analyzer.web.app import _resolve_account_id

_PLAYERS = [
    PlayerInfo(0, "おりーぶzz", account_id=42),
    PlayerInfo(1, "B"),
    PlayerInfo(2, "C"),
    PlayerInfo(3, "D"),
]


def _settings(tmp_path: Path, my_account_id: int | None = 42) -> Settings:
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
        my_account_id=my_account_id,
    )


def _seed_player(settings: Settings) -> None:
    game_log = GameLog(paipu_id="g1", players=_PLAYERS, events=[])
    with db.open_db(settings.db_path) as conn:
        db.record_parsed_game(conn, game_log)


def test_resolve_by_numeric_id(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed_player(settings)
    assert _resolve_account_id(settings, "42") == 42


def test_resolve_by_username(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed_player(settings)
    assert _resolve_account_id(settings, "おりーぶzz") == 42


def test_resolve_rejects_wrong_id(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed_player(settings)
    assert _resolve_account_id(settings, "99999") is None


def test_resolve_rejects_unknown_name(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed_player(settings)
    assert _resolve_account_id(settings, "知らない人") is None


def test_resolve_none_when_my_account_id_unset(tmp_path: Path) -> None:
    settings = _settings(tmp_path, my_account_id=None)
    assert _resolve_account_id(settings, "おりーぶzz") is None


def test_resolve_handles_empty_input(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _seed_player(settings)
    assert _resolve_account_id(settings, "") is None
    assert _resolve_account_id(settings, "   ") is None

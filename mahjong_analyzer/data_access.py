"""解析済み牌譜(data/parsed/*.json)の読み込み。CLI/Web UI双方から使う。"""

from __future__ import annotations

import json

from mahjong_analyzer.config import Settings
from mahjong_analyzer.parser.model import GameLog


def load_parsed_games(settings: Settings) -> list[GameLog]:
    parsed_files = sorted(settings.parsed_dir.glob("*.json"))
    return [GameLog.from_dict(json.loads(p.read_text(encoding="utf-8"))) for p in parsed_files]

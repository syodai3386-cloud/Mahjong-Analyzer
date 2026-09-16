"""分析対象の牌譜を絞り込むフィルター(直近N戦、期間指定)。CLI/Web UI共通。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from mahjong_analyzer.parser.model import GameLog


@dataclass(frozen=True)
class GameFilter:
    recent: int | None = None  # 直近N戦のみに絞る(start_time降順でN件)
    date_from: date | None = None  # この日を含めて以降
    date_to: date | None = None  # この日を含めて以前

    @property
    def is_active(self) -> bool:
        return self.recent is not None or self.date_from is not None or self.date_to is not None


def apply_filter(game_logs: list[GameLog], game_filter: GameFilter) -> list[GameLog]:
    """start_timeが無い(未取得)牌譜は、フィルター指定があれば対象外にする
    (期間や直近N戦を指定した以上、時刻不明な牌譜を含めるべきではないため)。
    フィルター未指定(is_active=False)の場合は全件をそのまま返す。
    """
    if not game_filter.is_active:
        return list(game_logs)

    dated = [gl for gl in game_logs if gl.start_time is not None]
    dated.sort(key=lambda gl: gl.start_time)

    if game_filter.date_from is not None:
        dated = [gl for gl in dated if date.fromtimestamp(gl.start_time) >= game_filter.date_from]
    if game_filter.date_to is not None:
        dated = [gl for gl in dated if date.fromtimestamp(gl.start_time) <= game_filter.date_to]
    if game_filter.recent is not None:
        dated = dated[-game_filter.recent :]

    return dated

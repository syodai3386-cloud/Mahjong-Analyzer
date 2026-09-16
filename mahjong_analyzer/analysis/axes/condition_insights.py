"""メンタル/コンディション傾向の裏付けとなる集計。

`condition.py`が作る「1局1点」の時系列は、単発では調子の波の証拠として弱い。
ここでは複数局をまたいだ切り口で束ねて集計し直し、「本当にコンディションの
影響がありそうか」を判断しやすくする:
  - セッション内で何局目かによる平均ミス率の変化(疲労・慣れの影響)
  - 直前の対局の着順による影響(悪い結果を引きずっていないか、いわゆる「引きずり」)
  - 時間帯による平均ミス率の変化(深夜プレイの影響など)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from mahjong_analyzer.analysis.axes.condition import GameCondition

_SESSION_POSITION_BUCKETS = ["1局目", "2局目", "3局目", "4局目", "5局目以降"]

_TIME_OF_DAY_ORDER = ["朝(5-12時)", "昼(12-18時)", "夜(18-24時)", "深夜(0-5時)"]


@dataclass
class Bucket:
    label: str
    avg_mistake_rate: float
    sample_size: int  # 対象局数


@dataclass
class ConditionInsights:
    by_session_position: list[Bucket]
    after_last_place: Bucket | None  # 直前の対局がラスだった場合
    after_other: Bucket | None  # 直前の対局がラス以外だった場合
    by_time_of_day: list[Bucket]


def _avg(rates: list[float]) -> float:
    return round(sum(rates) / len(rates), 3) if rates else 0.0


def _session_position_label(games_into_session: int) -> str:
    idx = min(games_into_session, 5) - 1
    return _SESSION_POSITION_BUCKETS[idx]


def _time_of_day_label(start_time: int) -> str:
    hour = datetime.fromtimestamp(start_time).hour
    if 5 <= hour < 12:
        return "朝(5-12時)"
    if 12 <= hour < 18:
        return "昼(12-18時)"
    if 18 <= hour < 24:
        return "夜(18-24時)"
    return "深夜(0-5時)"


def analyze_condition(
    timeline: list[GameCondition], rank_by_paipu: dict[str, int | None]
) -> ConditionInsights:
    # セッション内の何局目かによる平均ミス率
    position_groups: dict[str, list[float]] = {label: [] for label in _SESSION_POSITION_BUCKETS}
    for c in timeline:
        position_groups[_session_position_label(c.games_into_session)].append(c.mistake_rate)
    by_session_position = [
        Bucket(label=label, avg_mistake_rate=_avg(rates), sample_size=len(rates))
        for label, rates in position_groups.items()
    ]

    # 直前の対局(同一セッション内)がラスだったかどうかによる平均ミス率
    by_session: dict[int, list[GameCondition]] = {}
    for c in timeline:
        by_session.setdefault(c.session_index, []).append(c)

    after_last_rates: list[float] = []
    after_other_rates: list[float] = []
    for games in by_session.values():
        for i in range(1, len(games)):
            prev_rank = rank_by_paipu.get(games[i - 1].paipu_id)
            if prev_rank is None:
                continue
            (after_last_rates if prev_rank == 4 else after_other_rates).append(games[i].mistake_rate)

    after_last_place = (
        Bucket("前局がラスだった", _avg(after_last_rates), len(after_last_rates))
        if after_last_rates
        else None
    )
    after_other = (
        Bucket("前局がラス以外だった", _avg(after_other_rates), len(after_other_rates))
        if after_other_rates
        else None
    )

    # 時間帯による平均ミス率
    tod_groups: dict[str, list[float]] = {}
    for c in timeline:
        tod_groups.setdefault(_time_of_day_label(c.start_time), []).append(c.mistake_rate)
    by_time_of_day = [
        Bucket(label=label, avg_mistake_rate=_avg(tod_groups[label]), sample_size=len(tod_groups[label]))
        for label in _TIME_OF_DAY_ORDER
        if label in tod_groups
    ]

    return ConditionInsights(
        by_session_position=by_session_position,
        after_last_place=after_last_place,
        after_other=after_other,
        by_time_of_day=by_time_of_day,
    )

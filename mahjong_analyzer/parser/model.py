"""正規化された対局データのモデル定義。

イベント自体はmjai形式(https://mjai.app 系ツールで標準的なJSON Lines)に準拠した
辞書として表現する。これにより将来Mortal/mjai-reviewerなど既存OSSとの連携が
容易になる。GameLog/PlayerInfoはその周辺のメタデータを保持する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, TypedDict

# mjaiのイベントは type によってフィールドが異なる可変長JSONなので、
# 厳密なUnion型ではなくtotal=FalseのTypedDictで緩く表現する。
MjaiEvent = dict[str, Any]


class MjaiEventDict(TypedDict, total=False):
    type: str
    actor: int
    pai: str
    tsumogiri: bool
    consumed: list[str]
    target: int
    deltas: list[int]
    scores: list[int]
    reason: str
    names: list[str]
    kyoku: int
    honba: int
    kyotaku: int
    oya: int
    bakaze: str
    dora_marker: str
    tehais: list[list[str]]


@dataclass
class PlayerInfo:
    seat: int  # 0-3 (起家からの席順)
    name: str
    account_id: int | None = None


@dataclass
class GameLog:
    """1半荘/1局セットぶんの正規化ログ。"""

    paipu_id: str
    players: list[PlayerInfo]
    events: list[MjaiEvent] = field(default_factory=list)
    rule: dict[str, Any] = field(default_factory=dict)
    start_time: int | None = None  # unix epoch秒(雀魂head.start_time由来)。コンディション傾向分析用。
    end_time: int | None = None

    def player_name(self, seat: int) -> str:
        for p in self.players:
            if p.seat == seat:
                return p.name
        return f"seat{seat}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "paipu_id": self.paipu_id,
            "players": [
                {"seat": p.seat, "name": p.name, "account_id": p.account_id} for p in self.players
            ],
            "events": self.events,
            "rule": self.rule,
            "start_time": self.start_time,
            "end_time": self.end_time,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GameLog":
        players = [PlayerInfo(**p) for p in data.get("players", [])]
        return cls(
            paipu_id=data["paipu_id"],
            players=players,
            events=data.get("events", []),
            rule=data.get("rule", {}),
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
        )


def iter_kyoku(events: list[MjaiEvent]) -> Iterator[list[MjaiEvent]]:
    """イベント列を局(start_kyoku〜end_kyoku)単位に分割してイテレートする。"""
    current: list[MjaiEvent] | None = None
    for ev in events:
        etype = ev.get("type")
        if etype == "start_kyoku":
            current = [ev]
        elif current is not None:
            current.append(ev)
            if etype == "end_kyoku":
                yield current
                current = None
    if current:
        yield current

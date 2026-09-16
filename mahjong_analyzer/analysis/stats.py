"""複数対局にわたる統計集計(和了率・放銃率・平均順位・リーチ率・副露率など)。"""

from __future__ import annotations

from dataclasses import dataclass

from mahjong_analyzer.parser.model import GameLog, iter_kyoku

_CALL_TYPES = {"chi", "pon", "kan"}


@dataclass
class PlayerStats:
    name: str
    games: int = 0
    total_rank: int = 0
    total_kyoku: int = 0
    wins: int = 0
    deal_ins: int = 0
    riichi_count: int = 0
    call_count: int = 0
    win_score_total: int = 0
    deal_in_score_total: int = 0

    @property
    def avg_rank(self) -> float:
        return self.total_rank / self.games if self.games else 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_kyoku if self.total_kyoku else 0.0

    @property
    def deal_in_rate(self) -> float:
        return self.deal_ins / self.total_kyoku if self.total_kyoku else 0.0

    @property
    def riichi_rate(self) -> float:
        return self.riichi_count / self.total_kyoku if self.total_kyoku else 0.0

    @property
    def call_rate(self) -> float:
        return self.call_count / self.total_kyoku if self.total_kyoku else 0.0

    @property
    def avg_win_score(self) -> float:
        return self.win_score_total / self.wins if self.wins else 0.0

    @property
    def avg_deal_in_score(self) -> float:
        return self.deal_in_score_total / self.deal_ins if self.deal_ins else 0.0


def _get_or_create(stats: dict[str, PlayerStats], name: str) -> PlayerStats:
    if name not in stats:
        stats[name] = PlayerStats(name=name)
    return stats[name]


def game_rank_by_seat(game_log: GameLog) -> dict[int, int]:
    """対局の最終順位(1が トップ)を席番号ごとに返す。終局情報がなければ空dict。"""
    end_game = next((ev for ev in game_log.events if ev.get("type") == "end_game"), None)
    if not end_game or not end_game.get("scores"):
        return {}
    scores: list[int] = end_game["scores"]
    order = sorted(range(len(scores)), key=lambda seat: -scores[seat])
    return {seat: rank + 1 for rank, seat in enumerate(order)}


def _aggregate_one_game(gl: GameLog, stats: dict[str, PlayerStats]) -> None:
    seat_to_name = {p.seat: p.name for p in gl.players}
    for name in seat_to_name.values():
        _get_or_create(stats, name)

    for kyoku_events in iter_kyoku(gl.events):
        participants: set[int] = set()
        called: set[int] = set()
        riichi: set[int] = set()

        for ev in kyoku_events:
            etype = ev.get("type")
            if etype == "start_kyoku":
                participants = set(seat_to_name.keys())
            elif etype in _CALL_TYPES:
                called.add(ev["actor"])
            elif etype == "reach":
                riichi.add(ev["actor"])
            elif etype == "hora":
                actor = ev["actor"]
                target = ev.get("target", actor)
                deltas = ev.get("deltas")

                winner_name = seat_to_name.get(actor)
                if winner_name is not None:
                    winner = _get_or_create(stats, winner_name)
                    winner.wins += 1
                    if deltas:
                        winner.win_score_total += deltas[actor]

                if target != actor:
                    loser_name = seat_to_name.get(target)
                    if loser_name is not None:
                        loser = _get_or_create(stats, loser_name)
                        loser.deal_ins += 1
                        if deltas:
                            loser.deal_in_score_total += abs(deltas[target])

        for seat in participants:
            name = seat_to_name.get(seat)
            if name is None:
                continue
            p = _get_or_create(stats, name)
            p.total_kyoku += 1
            if seat in called:
                p.call_count += 1
            if seat in riichi:
                p.riichi_count += 1

    rank_by_seat = game_rank_by_seat(gl)
    if rank_by_seat:
        for seat, name in seat_to_name.items():
            p = _get_or_create(stats, name)
            p.games += 1
            p.total_rank += rank_by_seat.get(seat, 0)


def aggregate_stats(game_logs: list[GameLog]) -> dict[str, PlayerStats]:
    """複数のGameLogから、プレイヤー名をキーにした集計統計を作る。"""
    stats: dict[str, PlayerStats] = {}
    for gl in game_logs:
        _aggregate_one_game(gl, stats)
    return stats

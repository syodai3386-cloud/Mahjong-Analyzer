"""Mortal比較だけでは得られない、牌譜(GameLog)から直接分かる文脈情報の計算。

役割分担: 各判断のEV(良し悪しの度合い)を求めるのはMortal側の仕事、
「その判断がどんな状況(危険な場面か、何着目でオーラスかなど)で行われたか」
というラベル付けはこちら側の仕事、と分離している。

対応範囲について: 牌譜(GameLog)には実際に取られた行動しか記録されておらず、
「鳴かなかった」「リーチしなかった」という非選択は明示的なイベントとして
残らない。そのためここでの文脈付けは decision_type == "dahai"(打牌)の
判断ポイントのみを対象とする。鳴き/リーチ判断への文脈付けは、実際に
Mortalを動かして出力の並び方を確認できてから拡張する。
"""

from __future__ import annotations

from dataclasses import dataclass

from mahjong_analyzer.parser.model import GameLog, MjaiEvent, iter_kyoku
from mahjong_analyzer.review.mortal_client import MortalDecision


@dataclass
class DecisionContext:
    is_defending: bool  # 自分以外に進行中のリーチがあるか
    rank_at_decision: int | None  # その時点の暫定順位(1が トップ)
    is_all_last: bool  # 南4局(オーラス)以降か
    riichi_discards: frozenset[str]  # 進行中のリーチ者(自分以外)の捨て牌の和集合(=現物)


def _rank_of(seat: int, scores: list[int]) -> int:
    return 1 + sum(1 for other, s in enumerate(scores) if other != seat and s > scores[seat])


def _kyoku_context(events: list[MjaiEvent]) -> dict[tuple[int, int], DecisionContext]:
    """(actor, turn) -> DecisionContext のマップを1局ぶん作る。"""
    context: dict[tuple[int, int], DecisionContext] = {}
    riichi_seats: set[int] = set()
    turn_counter: dict[int, int] = {}
    discards_by_seat: dict[int, list[str]] = {}
    scores: list[int] | None = None
    is_all_last = False

    for ev in events:
        etype = ev.get("type")
        if etype == "start_kyoku":
            scores = ev.get("scores")
            bakaze = ev.get("bakaze", "E")
            kyoku_num = ev.get("kyoku", 1)
            is_all_last = bakaze == "S" and kyoku_num >= 4
        elif etype == "dahai":
            actor = ev["actor"]
            turn_counter[actor] = turn_counter.get(actor, 0) + 1
            other_riichi = riichi_seats - {actor}
            riichi_discards = frozenset(
                tile for seat in other_riichi for tile in discards_by_seat.get(seat, [])
            )
            context[(actor, turn_counter[actor])] = DecisionContext(
                is_defending=bool(other_riichi),
                rank_at_decision=_rank_of(actor, scores) if scores else None,
                is_all_last=is_all_last,
                riichi_discards=riichi_discards,
            )
            discards_by_seat.setdefault(actor, []).append(ev["pai"])
        elif etype == "reach":
            riichi_seats.add(ev["actor"])

    return context


def compute_context(game_log: GameLog) -> dict[tuple[int, int, int], DecisionContext]:
    """(kyoku_index, actor, turn) -> DecisionContext のマップを対局全体で作る。"""
    full: dict[tuple[int, int, int], DecisionContext] = {}
    for kyoku_index, kyoku_events in enumerate(iter_kyoku(game_log.events)):
        for (actor, turn), ctx in _kyoku_context(kyoku_events).items():
            full[(kyoku_index, actor, turn)] = ctx
    return full


def count_attacking_dahai(game_log: GameLog, seat: int) -> int:
    """指定した席の打牌のうち、防御中でなかった(攻めていた)打牌数を数える。

    牌効率は「速度を追う価値がある場面」でのみ意味を持つ指標であり、他家の
    リーチ等を受けて降りている最中はシャンテンが落ちて当然なので、牌効率の
    分母(何回の打牌中何回ミスしたか)は攻めていた打牌だけに絞る。
    """
    context = compute_context(game_log)
    return sum(1 for (_, actor, _), ctx in context.items() if actor == seat and not ctx.is_defending)


def enrich_with_context(game_log: GameLog, decisions: list[MortalDecision]) -> list[MortalDecision]:
    """MortalDecisionのis_defending/rank_at_decision/is_all_lastを、
    game_logから計算した文脈情報で埋める(dahai判断のみ、その場でmutateする)。"""
    context = compute_context(game_log)
    for d in decisions:
        if d.decision_type != "dahai":
            continue
        ctx = context.get((d.kyoku_index, d.actor, d.turn))
        if ctx is not None:
            d.is_defending = ctx.is_defending
            d.rank_at_decision = ctx.rank_at_decision
            d.is_all_last = ctx.is_all_last
    return decisions

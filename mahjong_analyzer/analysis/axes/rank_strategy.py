"""着順/点数状況判断軸: 局開始時点の暫定順位・オーラスか否かでEVロスをグルーピングする。

単発の押し引き軸とは異なり、「今何着目でどういう状況か」という半荘全体の
戦略文脈ごとに判断精度が変わっていないかを見る。
"""

from __future__ import annotations

from dataclasses import dataclass

from mahjong_analyzer.analysis.axes.base import AxisScore, summarize
from mahjong_analyzer.review.mortal_client import MortalDecision


@dataclass
class RankStrategyReport:
    overall: AxisScore
    by_rank: dict[int, AxisScore]
    all_last: AxisScore


def rank_strategy_axis(decisions: list[MortalDecision]) -> RankStrategyReport:
    dahai = [
        d for d in decisions if d.decision_type == "dahai" and d.rank_at_decision is not None
    ]
    by_rank = {
        rank: summarize(f"{rank}位時", [d for d in dahai if d.rank_at_decision == rank])
        for rank in (1, 2, 3, 4)
    }
    all_last = summarize("オーラス", [d for d in dahai if d.is_all_last])
    return RankStrategyReport(
        overall=summarize("着順/点数状況判断", dahai), by_rank=by_rank, all_last=all_last
    )

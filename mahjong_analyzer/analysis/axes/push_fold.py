"""押し引き軸: 他家リーチ等の危険な状況下での打牌のEVロスを評価する。"""

from __future__ import annotations

from mahjong_analyzer.analysis.axes.base import AxisScore, summarize
from mahjong_analyzer.review.mortal_client import MortalDecision


def push_fold_axis(decisions: list[MortalDecision]) -> AxisScore:
    defending = [d for d in decisions if d.decision_type == "dahai" and d.is_defending]
    return summarize("押し引き", defending)

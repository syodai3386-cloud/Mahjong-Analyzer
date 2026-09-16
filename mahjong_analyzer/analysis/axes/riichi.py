"""リーチ判断軸: リーチ宣言(reach)のEVロスを評価する。

鳴き判断軸と同じ理由(牌譜には実行動のみが残る)で、現状はリーチした
判断のみが対象。「リーチすべきだったのにダマにした」見逃しの検出は、
Mortalの出力形式を実データで確認してから拡張する。
"""

from __future__ import annotations

from mahjong_analyzer.analysis.axes.base import AxisScore, summarize
from mahjong_analyzer.review.mortal_client import MortalDecision


def riichi_axis(decisions: list[MortalDecision]) -> AxisScore:
    reaches = [d for d in decisions if d.decision_type == "reach"]
    return summarize("リーチ判断", reaches)

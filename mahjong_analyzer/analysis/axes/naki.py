"""鳴き判断軸: チー・ポン・カンを選んだ判断のEVロスを評価する。

牌譜(GameLog)には実際に取られた行動しか残らず、「鳴かなかった」という
非選択は記録されないため、現状は実際に鳴いた判断のみが対象。スルーの
是非を含めた評価は、Mortalの出力形式を実データで確認してから拡張する。
"""

from __future__ import annotations

from mahjong_analyzer.analysis.axes.base import AxisScore, summarize
from mahjong_analyzer.review.mortal_client import MortalDecision

_CALL_TYPES = {"chi", "pon", "kan", "ankan", "kakan"}


def naki_axis(decisions: list[MortalDecision]) -> AxisScore:
    calls = [d for d in decisions if d.decision_type in _CALL_TYPES]
    return summarize("鳴き判断", calls)

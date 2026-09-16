"""手役・打点構築判断軸: 牌効率(最速)上は「ミス」とされる打牌が、実際には
打点を優先した意図的な選択だったのか、それとも純粋な失着だったのかを、
牌効率の判定(analysis.efficiency)とMortalのEV評価を突き合わせて分類する。

分類:
  - 効率的に最善(=牌効率ミスに該当しない)                          -> 対象外
  - 効率は劣るが実打牌がMortalの最善手と一致                        -> 打点重視の妥当な選択
  - 効率も劣りMortalの最善手とも異なる(実打牌がbest_choiceと不一致)  -> 純粋な失着
"""

from __future__ import annotations

from dataclasses import dataclass

from mahjong_analyzer.analysis.efficiency import DiscardMistake
from mahjong_analyzer.review.mortal_client import MortalDecision


@dataclass
class HandValueReport:
    efficiency_mistakes: int
    value_favoring: int
    pure_mistakes: int
    unmatched: int  # 対応するMortal判断データが見つからなかった件数

    @property
    def value_favoring_rate(self) -> float:
        judged = self.value_favoring + self.pure_mistakes
        return self.value_favoring / judged if judged else 0.0


def classify_hand_value_decisions(
    efficiency_mistakes: list[DiscardMistake], mortal_decisions: list[MortalDecision]
) -> HandValueReport:
    mortal_by_key = {
        (d.kyoku_index, d.turn, d.actor): d
        for d in mortal_decisions
        if d.decision_type == "dahai"
    }

    value_favoring = 0
    pure_mistakes = 0
    unmatched = 0
    for m in efficiency_mistakes:
        md = mortal_by_key.get((m.kyoku_index, m.turn, m.actor))
        if md is None:
            unmatched += 1
            continue
        if md.actual_choice == md.best_choice:
            value_favoring += 1
        else:
            pure_mistakes += 1

    return HandValueReport(
        efficiency_mistakes=len(efficiency_mistakes),
        value_favoring=value_favoring,
        pure_mistakes=pure_mistakes,
        unmatched=unmatched,
    )

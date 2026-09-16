"""降り技術の質: 押し引き軸のうち「危険な状況で打牌した」判断について、
選んだ牌が現物(進行中のリーチ者がすでに切っている100%安全な牌)だったかを見る。

現物を切らずに済ませている(＝現物以外の牌を選んでいる)判断のうち、EVロスが
大きいものは、危険牌の見極め(スジ・壁読み等)が甘かった可能性を示す。
"""

from __future__ import annotations

from dataclasses import dataclass

from mahjong_analyzer.analysis.axes.context import compute_context
from mahjong_analyzer.parser.model import GameLog
from mahjong_analyzer.review.mortal_client import MortalDecision


@dataclass
class DefenseQualityReport:
    defending_decisions: int
    genbutsu_choices: int
    total_non_genbutsu_ev_loss: float  # 複数局を合算する際は、これをsumしてnon_genbutsu件数の合計で割る

    @property
    def genbutsu_rate(self) -> float:
        return self.genbutsu_choices / self.defending_decisions if self.defending_decisions else 0.0

    @property
    def non_genbutsu_count(self) -> int:
        return self.defending_decisions - self.genbutsu_choices

    @property
    def non_genbutsu_avg_ev_loss(self) -> float:
        return self.total_non_genbutsu_ev_loss / self.non_genbutsu_count if self.non_genbutsu_count else 0.0


def defense_quality_axis(game_log: GameLog, decisions: list[MortalDecision]) -> DefenseQualityReport:
    context = compute_context(game_log)
    defending = [d for d in decisions if d.decision_type == "dahai" and d.is_defending]

    genbutsu_choices = 0
    total_non_genbutsu_ev_loss = 0.0
    for d in defending:
        ctx = context.get((d.kyoku_index, d.actor, d.turn))
        if ctx is None:
            continue
        if d.actual_choice in ctx.riichi_discards:
            genbutsu_choices += 1
        else:
            total_non_genbutsu_ev_loss += d.ev_loss

    return DefenseQualityReport(
        defending_decisions=len(defending),
        genbutsu_choices=genbutsu_choices,
        total_non_genbutsu_ev_loss=total_non_genbutsu_ev_loss,
    )

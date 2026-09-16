"""評価軸の共通データ構造・集計ロジック。"""

from __future__ import annotations

from dataclasses import dataclass

from mahjong_analyzer.review.mortal_client import MortalDecision


@dataclass
class AxisScore:
    name: str
    sample_size: int
    avg_ev_loss: float
    mistake_rate: float  # ev_loss > 0 の判断が占める割合


def summarize(name: str, decisions: list[MortalDecision]) -> AxisScore:
    if not decisions:
        return AxisScore(name=name, sample_size=0, avg_ev_loss=0.0, mistake_rate=0.0)
    losses = [d.ev_loss for d in decisions]
    mistakes = sum(1 for loss in losses if loss > 0)
    return AxisScore(
        name=name,
        sample_size=len(decisions),
        avg_ev_loss=sum(losses) / len(losses),
        mistake_rate=mistakes / len(losses),
    )

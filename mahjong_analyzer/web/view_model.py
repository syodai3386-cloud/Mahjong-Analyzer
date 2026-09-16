"""ダッシュボード表示専用の変換ロジック。

`analysis.report.ScoreReport`(分析データそのもの)と、テンプレートが必要と
する表示用の形(横並びカード・ランキング・ドリルダウン用の明細行)を分離する層。
CLIからは使わない(Web UI固有のプレゼンテーション関心事のため)。
"""

from __future__ import annotations

from dataclasses import dataclass

from mahjong_analyzer.analysis.efficiency import MISTAKE_CATEGORIES, MISTAKE_CATEGORY_DESCRIPTIONS, classify_mistake
from mahjong_analyzer.analysis.report import ScoreReport
from mahjong_analyzer.analysis.scoring import accuracy_score, weighted_overall_score


@dataclass
class AxisCard:
    key: str
    label: str
    score: float | None  # 0〜100。Noneはまだデータがない(review未実行等)。
    sample_size: int

    @property
    def available(self) -> bool:
        return self.score is not None


def build_axis_cards(report: ScoreReport) -> list[AxisCard]:
    """「総合評価」を除く、各評価軸のカードを並び順どおりに返す。"""
    hand_value_n = report.hand_value.value_favoring + report.hand_value.pure_mistakes
    return [
        AxisCard(
            "efficiency", "牌効率",
            report.efficiency_accuracy if report.total_dahai else None,
            report.total_dahai,
        ),
        AxisCard(
            "push_fold", "押し引き",
            accuracy_score(report.push_fold.mistake_rate) if report.push_fold.sample_size else None,
            report.push_fold.sample_size,
        ),
        AxisCard(
            "naki", "鳴き判断",
            accuracy_score(report.naki.mistake_rate) if report.naki.sample_size else None,
            report.naki.sample_size,
        ),
        AxisCard(
            "riichi", "リーチ判断",
            accuracy_score(report.riichi.mistake_rate) if report.riichi.sample_size else None,
            report.riichi.sample_size,
        ),
        AxisCard(
            "rank_strategy", "着順/点数状況判断",
            accuracy_score(report.rank_strategy.overall.mistake_rate)
            if report.rank_strategy.overall.sample_size else None,
            report.rank_strategy.overall.sample_size,
        ),
        AxisCard(
            "hand_value", "手役・打点構築判断",
            round(report.hand_value.value_favoring_rate * 100, 1) if hand_value_n else None,
            hand_value_n,
        ),
    ]


def build_overall_card(cards: list[AxisCard]) -> AxisCard:
    available = [c for c in cards if c.available]
    score = weighted_overall_score([(c.score, c.sample_size) for c in available])
    return AxisCard("overall", "総合評価", score, sum(c.sample_size for c in available))


@dataclass
class MistakeCategoryBucket:
    label: str
    description: str
    count: int
    avg_ukeire_loss: float


def mistake_category_breakdown(report: ScoreReport) -> list[MistakeCategoryBucket]:
    """牌効率ミスを重症度別(シャンテン後退/受け入れの大きな見落とし/わずかな見落とし)に
    分類し、重い順に並べる。"""
    groups: dict[str, list] = {label: [] for label in MISTAKE_CATEGORIES}
    for m in report.all_mistakes:
        groups[classify_mistake(m)].append(m)

    buckets = []
    for label in MISTAKE_CATEGORIES:
        ms = groups[label]
        avg_loss = round(sum(m.ukeire_loss for m in ms) / len(ms), 1) if ms else 0.0
        buckets.append(
            MistakeCategoryBucket(
                label=label,
                description=MISTAKE_CATEGORY_DESCRIPTIONS[label],
                count=len(ms),
                avg_ukeire_loss=avg_loss,
            )
        )
    return buckets


def mistake_detail_rows(report: ScoreReport, date_by_paipu: dict[str, str]) -> list[dict]:
    """牌効率ミスの明細行(ドリルダウン表示用)。損失(受け入れ差)が大きい順。"""
    rows = []
    for paipu_id, mistakes in report.mistakes_by_paipu.items():
        date_label = date_by_paipu.get(paipu_id, paipu_id)
        for m in mistakes:
            rows.append(
                {
                    "date": date_label,
                    "kyoku": m.kyoku_index + 1,
                    "turn": m.turn,
                    "discarded": m.discarded,
                    "best_discard": m.best_discard,
                    "shanten_actual": m.shanten_after_actual,
                    "shanten_best": m.shanten_after_best,
                    "ukeire_loss": m.ukeire_loss,
                    "category": classify_mistake(m),
                }
            )
    rows.sort(key=lambda r: r["ukeire_loss"], reverse=True)
    return rows

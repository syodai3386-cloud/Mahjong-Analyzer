"""各評価軸の生スコアを偏差値化する。

他プレイヤーとの比較データは持たない(①のスコープを自分専用ツールに
限定した決定と整合)ため、ここでの偏差値は「自分の全対局データの分布内での
相対位置」を表す。将来、他プレイヤーの牌譜が蓄積されればそのまま母集団を
差し替えられる設計にしてある。
"""

from __future__ import annotations

import statistics


def to_deviation_values(raw_scores: list[float], *, higher_is_better: bool = False) -> list[float]:
    """生スコアのリストを平均50・標準偏差10の偏差値に変換する。

    :param raw_scores: 例えば「1半荘ごとのEVロス平均」のような数値列。
    :param higher_is_better: Falseの場合、値が小さいほど高偏差値になる
        (EVロスやミス率など「小さいほど良い」指標向けのデフォルト)。
    """
    if not raw_scores:
        return []
    mean = statistics.fmean(raw_scores)
    stdev = statistics.pstdev(raw_scores)
    if stdev == 0:
        return [50.0 for _ in raw_scores]
    sign = 1 if higher_is_better else -1
    return [50 + sign * 10 * (x - mean) / stdev for x in raw_scores]


def accuracy_score(mistake_rate: float) -> float:
    """ミス率(0〜1)を「正解率」スコア(0〜100、高いほど良い)に変換する。

    UIで各評価軸を横並びのカードとして一覧表示する際の、直感的な単一指標として使う。
    """
    return round((1 - mistake_rate) * 100, 1)


def weighted_overall_score(scores_and_weights: list[tuple[float, int]]) -> float | None:
    """各評価軸のスコア(0〜100)とサンプル数(重み)から、総合評価スコアを算出する。

    サンプル数0の軸(まだデータがない)は除外する。全軸が空ならNoneを返す。
    """
    usable = [(score, weight) for score, weight in scores_and_weights if weight > 0]
    if not usable:
        return None
    total_weight = sum(weight for _, weight in usable)
    return round(sum(score * weight for score, weight in usable) / total_weight, 1)

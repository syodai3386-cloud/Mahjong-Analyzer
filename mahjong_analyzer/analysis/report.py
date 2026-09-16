"""全評価軸を集計した`ScoreReport`の構築。CLI(`score`コマンド)とWeb UIの
両方から同じ集計結果を使うための共通ロジック。
"""

from __future__ import annotations

from dataclasses import dataclass

from mahjong_analyzer.analysis.axes.base import AxisScore
from mahjong_analyzer.analysis.axes.condition import GameCondition, compute_condition_timeline
from mahjong_analyzer.analysis.axes.condition_insights import ConditionInsights, analyze_condition
from mahjong_analyzer.analysis.axes.context import compute_context
from mahjong_analyzer.analysis.axes.defense_quality import defense_quality_axis
from mahjong_analyzer.analysis.axes.hand_value import HandValueReport, classify_hand_value_decisions
from mahjong_analyzer.analysis.axes.naki import naki_axis
from mahjong_analyzer.analysis.axes.push_fold import push_fold_axis
from mahjong_analyzer.analysis.axes.rank_strategy import RankStrategyReport, rank_strategy_axis
from mahjong_analyzer.analysis.axes.riichi import riichi_axis
from mahjong_analyzer.analysis.efficiency import DiscardMistake
from mahjong_analyzer.analysis.stats import game_rank_by_seat
from mahjong_analyzer.config import Settings
from mahjong_analyzer.data_access import load_parsed_games
from mahjong_analyzer.parser.model import GameLog
from mahjong_analyzer.review.mortal_client import MortalDecision
from mahjong_analyzer.storage import db


def my_seat(settings: Settings, game_log: GameLog) -> int | None:
    if settings.my_account_id is None:
        return None
    return next((p.seat for p in game_log.players if p.account_id == settings.my_account_id), None)


@dataclass
class DefenseQualitySummary:
    defending_decisions: int
    genbutsu_choices: int
    non_genbutsu_avg_ev_loss: float

    @property
    def genbutsu_rate(self) -> float:
        return self.genbutsu_choices / self.defending_decisions if self.defending_decisions else 0.0


@dataclass
class ScoreReport:
    games_count: int
    total_mistakes: int
    total_dahai: int
    mistakes_by_paipu: dict[str, list[DiscardMistake]]
    excluded_defending_count: int  # 防御中のシャンテン低下等として牌効率ミスから除外した件数
    excluded_dora_justified_count: int  # 打点(ドラ)重視の妥当な選択として除外した件数
    has_mortal_data: bool
    push_fold: AxisScore
    naki: AxisScore
    riichi: AxisScore
    rank_strategy: RankStrategyReport
    hand_value: HandValueReport
    defense_quality: DefenseQualitySummary
    condition_timeline: list[GameCondition]
    condition_insights: ConditionInsights

    @property
    def efficiency_accuracy(self) -> float:
        """牌効率の「ミスなし打牌」の割合(0〜100)。他の軸と並べて表示するための指標。"""
        if not self.total_dahai:
            return 0.0
        return round((1 - self.total_mistakes / self.total_dahai) * 100, 1)

    @property
    def all_mistakes(self) -> list[DiscardMistake]:
        return [m for ms in self.mistakes_by_paipu.values() for m in ms]


def build_score_report(settings: Settings, game_logs: list[GameLog] | None = None) -> ScoreReport:
    """全評価軸を集計する。`settings.my_account_id`が設定済みで、解析済み
    牌譜(data/parsed/)が1件以上ある前提(呼び出し側で事前にチェックすること)。

    `game_logs`を渡すとその牌譜集合だけを対象にする(`filters.apply_filter`で
    絞り込んだ結果を渡す用途)。省略時は`data/parsed/`の全件を読み込む。
    """
    if game_logs is None:
        game_logs = load_parsed_games(settings)

    my_decisions: list[MortalDecision] = []
    my_decisions_by_game: dict[str, list[MortalDecision]] = {}
    my_mistakes_by_game: dict[str, list[DiscardMistake]] = {}
    attacking_dahai_by_paipu: dict[str, int] = {}
    total_dahai = 0
    excluded_defending_count = 0
    excluded_dora_justified_count = 0
    with db.open_db(settings.db_path) as conn:
        for gl in game_logs:
            seat = my_seat(settings, gl)
            if seat is None:
                continue
            rows = db.fetch_mortal_decisions(conn, gl.paipu_id)
            game_decisions = [
                d for row in rows if (d := db.mortal_decision_from_row(row)).actor == seat
            ]
            my_decisions.extend(game_decisions)
            if game_decisions:
                my_decisions_by_game[gl.paipu_id] = game_decisions

            # `mistakes`テーブルは`mistakes`コマンドが保存したキャッシュ。
            # find_mistakes()のシャンテン計算は牌譜数が多いと重いため、ここでは
            # 都度再計算せずDBの結果を読む(`mistakes`コマンドを先に実行しておく前提)。
            mistake_rows = db.fetch_mistakes(conn, gl.paipu_id)
            raw_mistakes = [
                m for row in mistake_rows if (m := db.mistake_from_row(row)).actor == seat
            ]

            # 牌効率は「牌効率が意味を持つ場面(攻めている場面)」でのみ判断軸として
            # 使う。context.pyの防御文脈と、ドラ枚数比較による打点正当化判定の
            # 両方で、本質的にはミスとは言えないケースを除外する。
            context = compute_context(gl)
            kept: list[DiscardMistake] = []
            for m in raw_mistakes:
                ctx = context.get((m.kyoku_index, m.actor, m.turn))
                if ctx is not None and ctx.is_defending:
                    excluded_defending_count += 1
                    continue
                if m.is_dora_justified_shanten_loss:
                    excluded_dora_justified_count += 1
                    continue
                kept.append(m)
            my_mistakes_by_game[gl.paipu_id] = kept

            attacking_dahai = sum(
                1 for (_, a, _), ctx in context.items() if a == seat and not ctx.is_defending
            )
            attacking_dahai_by_paipu[gl.paipu_id] = attacking_dahai
            total_dahai += attacking_dahai
    all_mistakes = [m for ms in my_mistakes_by_game.values() for m in ms]

    defending_total = genbutsu_total = non_genbutsu_count_total = 0
    total_non_genbutsu_ev_loss = 0.0
    for gl in game_logs:
        game_decisions = my_decisions_by_game.get(gl.paipu_id)
        if not game_decisions:
            continue
        dq = defense_quality_axis(gl, game_decisions)
        defending_total += dq.defending_decisions
        genbutsu_total += dq.genbutsu_choices
        non_genbutsu_count_total += dq.non_genbutsu_count
        total_non_genbutsu_ev_loss += dq.total_non_genbutsu_ev_loss

    condition_timeline = compute_condition_timeline(
        game_logs,
        settings.my_account_id,
        mistakes_by_paipu=my_mistakes_by_game,
        attacking_dahai_by_paipu=attacking_dahai_by_paipu,
    )
    rank_by_paipu = {
        gl.paipu_id: game_rank_by_seat(gl).get(seat)
        for gl in game_logs
        if (seat := my_seat(settings, gl)) is not None
    }

    return ScoreReport(
        games_count=len(my_mistakes_by_game),
        total_mistakes=len(all_mistakes),
        total_dahai=total_dahai,
        mistakes_by_paipu=my_mistakes_by_game,
        excluded_defending_count=excluded_defending_count,
        excluded_dora_justified_count=excluded_dora_justified_count,
        has_mortal_data=bool(my_decisions),
        push_fold=push_fold_axis(my_decisions),
        naki=naki_axis(my_decisions),
        riichi=riichi_axis(my_decisions),
        rank_strategy=rank_strategy_axis(my_decisions),
        hand_value=classify_hand_value_decisions(all_mistakes, my_decisions),
        defense_quality=DefenseQualitySummary(
            defending_decisions=defending_total,
            genbutsu_choices=genbutsu_total,
            non_genbutsu_avg_ev_loss=(
                total_non_genbutsu_ev_loss / non_genbutsu_count_total if non_genbutsu_count_total else 0.0
            ),
        ),
        condition_timeline=condition_timeline,
        condition_insights=analyze_condition(condition_timeline, rank_by_paipu),
    )

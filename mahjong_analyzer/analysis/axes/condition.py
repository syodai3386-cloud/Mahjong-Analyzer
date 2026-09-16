"""メンタル/コンディション傾向軸: 連戦時・大敗直後などで判断精度(牌効率ミス率)が
落ちていないかを、対局開始時刻の時系列で見る。

他の軸と異なりMortalは不要で、既存の牌効率ミス検出(analysis.efficiency)と
GameLog.start_time/end_timeだけで計算できる。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from mahjong_analyzer.analysis.efficiency import DiscardMistake, find_mistakes
from mahjong_analyzer.parser.model import GameLog

# この間隔以上、前の対局の終了から間が空いていれば別セッション(別の日/休憩後)とみなす。
_SESSION_GAP_SECONDS = 60 * 60


@dataclass
class GameCondition:
    paipu_id: str
    start_time: int
    session_index: int
    games_into_session: int  # そのセッション内で何局目か(1始まり)
    mistake_rate: float  # 自分の総打牌数に対する牌効率ミス数の割合

    @property
    def date_label(self) -> str:
        """paipu_id(ハッシュ列で読みづらい)の代わりに表示する、実際の対局日時。"""
        return datetime.fromtimestamp(self.start_time).strftime("%Y/%m/%d %H:%M")

    @property
    def short_date_label(self) -> str:
        return datetime.fromtimestamp(self.start_time).strftime("%m/%d")


def compute_condition_timeline(
    game_logs: list[GameLog],
    account_id: int,
    mistakes_by_paipu: dict[str, list[DiscardMistake]] | None = None,
    attacking_dahai_by_paipu: dict[str, int] | None = None,
) -> list[GameCondition]:
    """`mistakes_by_paipu`(paipu_id -> 自分の牌効率ミス一覧、既にactorで絞り込み済み)を
    渡すとDBキャッシュ済みの結果を使い、渡さない場合はここで`find_mistakes`を都度
    再計算する(牌譜が多いと`analysis.efficiency.find_mistakes`のシャンテン計算が
    重いので、`analysis.report.build_score_report`はDBの`mistakes`テーブルから
    読み込んだ結果を渡して再計算を避けている)。

    `attacking_dahai_by_paipu`(paipu_id -> 攻めていた打牌数)を渡すと、ミス率の
    分母を「牌効率が意味を持つ場面(防御中でない場面)」だけに絞る。省略時は
    全打牌数を分母にする(`analysis.axes.context.count_attacking_dahai`未使用の
    簡易呼び出し向け)。
    """
    dated = [gl for gl in game_logs if gl.start_time is not None]
    dated.sort(key=lambda gl: gl.start_time)

    timeline: list[GameCondition] = []
    session_index = -1
    prev_end: int | None = None
    games_into_session = 0

    for gl in dated:
        seat = next((p.seat for p in gl.players if p.account_id == account_id), None)
        if seat is None:
            continue

        if prev_end is None or gl.start_time - prev_end > _SESSION_GAP_SECONDS:
            session_index += 1
            games_into_session = 0
        games_into_session += 1
        prev_end = gl.end_time if gl.end_time is not None else gl.start_time

        if attacking_dahai_by_paipu is not None:
            total_dahai = attacking_dahai_by_paipu.get(gl.paipu_id, 0)
        else:
            total_dahai = sum(
                1 for ev in gl.events if ev.get("type") == "dahai" and ev.get("actor") == seat
            )
        if mistakes_by_paipu is not None:
            own_mistakes = mistakes_by_paipu.get(gl.paipu_id, [])
        else:
            own_mistakes = [m for m in find_mistakes(gl) if m.actor == seat]
        rate = len(own_mistakes) / total_dahai if total_dahai else 0.0

        timeline.append(
            GameCondition(
                paipu_id=gl.paipu_id,
                start_time=gl.start_time,
                session_index=session_index,
                games_into_session=games_into_session,
                mistake_rate=rate,
            )
        )

    return timeline

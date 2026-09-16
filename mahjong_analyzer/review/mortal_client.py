"""Mortal AIをサブプロセスとして呼び出し、q_values(候補手ごとのEV)ベースの
判断ポイント評価(MortalDecision)を作る。

呼び出し方式は環境によって変える必要がある(現在の開発機はRAM 3.8GBで
Docker Desktopの常駐VMが厳しいためネイティブ実行を優先、32GB RAM移行後は
Dockerも選べるようにする)ため、`MortalEngine` を薄い抽象にしている。

ライセンス上の注意: MortalはAGPL-3.0。本モジュールはMortalの実行ファイルを
外部プロセスとして呼び出すだけで、コードをリンクしない。
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

from mahjong_analyzer.parser.model import GameLog
from mahjong_analyzer.review.mjai_export import to_mjai_events


@dataclass
class MortalDecision:
    kyoku_index: int
    turn: int
    actor: int
    decision_type: str  # "dahai" | "reach" | "pon" | "chi" | "kan" | "kyushu"
    actual_choice: str
    actual_q: float
    best_choice: str
    best_q: float
    shanten: int | None
    # 以下はMortalの出力には含まれない文脈情報。デフォルトで空にしておき、
    # analysis.axes.context.enrich_with_context() でgame_logから計算して後付けする。
    is_defending: bool = False
    rank_at_decision: int | None = None
    is_all_last: bool = False

    @property
    def ev_loss(self) -> float:
        return max(0.0, self.best_q - self.actual_q)


class MortalEngine(Protocol):
    """Mortalプロセスとの1回のやり取り(1局×1視点)を表すインターフェース。"""

    def run(self, mjai_jsonl: str) -> list[dict]:
        """mjai JSON Linesを渡し、Mortalが出力した各判断ポイントのJSON行を返す。"""
        ...


class NativeMortalEngine:
    """`cargo build --release` 等でネイティブビルドしたMortalバイナリを直接起動する実装。

    現状ローカル環境(RAM 3.8GB)ではRustツールチェーンのビルドが未実施のため
    未検証。`binary_path` が存在しない場合は `MortalNotAvailableError` を送出する。
    """

    def __init__(self, binary_path: Path, model_path: Path, config_path: Path | None = None):
        self.binary_path = binary_path
        self.model_path = model_path
        self.config_path = config_path

    def _check_available(self) -> None:
        if not self.binary_path.exists():
            raise MortalNotAvailableError(
                f"Mortalの実行ファイルが見つかりません: {self.binary_path}\n"
                "RAM増設後にRust/maturinでのネイティブビルド、またはDockerイメージの"
                "セットアップを行ってください。"
            )
        if not self.model_path.exists():
            raise MortalNotAvailableError(f"Mortalのモデルファイルが見つかりません: {self.model_path}")

    def run(self, mjai_jsonl: str) -> list[dict]:
        self._check_available()
        cmd = [str(self.binary_path)]
        if self.config_path is not None:
            cmd += ["--config", str(self.config_path)]

        proc = subprocess.run(
            cmd,
            input=mjai_jsonl,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Mortalプロセスがエラー終了しました: {proc.stderr}")

        return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


class MortalNotAvailableError(RuntimeError):
    """Mortal実行ファイル/モデルが未セットアップの環境で送出される。"""


def _extract_q_values(meta: dict) -> dict[str, float]:
    """Mortal出力の `meta.q_values` を {候補: EV} の辞書に正規化する。

    Mortalの実出力フォーマット(候補の並び順やキーの形が牌種インデックスか
    牌文字列か)は未検証。実データで確認でき次第このパース処理を調整する。
    """
    q_values = meta.get("q_values", {})
    if isinstance(q_values, dict):
        return {str(k): float(v) for k, v in q_values.items()}
    return {}


def build_decisions_for_seat(
    game_log: GameLog, perspective_seat: int, engine: MortalEngine
) -> list[MortalDecision]:
    """1局・1視点ぶんのMortalレビュー結果を、DBに保存できる形に変換する。"""
    mjai_jsonl = "\n".join(json.dumps(ev, ensure_ascii=False) for ev in to_mjai_events(game_log, perspective_seat))
    outputs = engine.run(mjai_jsonl + "\n")

    turn_counter = 0
    kyoku_index = -1
    decisions: list[MortalDecision] = []

    for out in outputs:
        if out.get("type") == "start_kyoku":
            kyoku_index += 1
            turn_counter = 0
            continue
        if out.get("actor") != perspective_seat:
            continue

        decision_type = out.get("type", "")
        meta = out.get("meta", {})
        q_values = _extract_q_values(meta)
        if not q_values:
            continue

        turn_counter += 1
        actual_choice = str(out.get("pai") or decision_type)
        actual_q = q_values.get(actual_choice, min(q_values.values()))
        best_choice = max(q_values, key=lambda k: q_values[k])
        best_q = q_values[best_choice]

        decisions.append(
            MortalDecision(
                kyoku_index=max(kyoku_index, 0),
                turn=turn_counter,
                actor=perspective_seat,
                decision_type=decision_type,
                actual_choice=actual_choice,
                actual_q=actual_q,
                best_choice=best_choice,
                best_q=best_q,
                shanten=meta.get("shanten"),
            )
        )

    return decisions


def review_game(
    game_log: GameLog, engine: MortalEngine, seats: Iterable[int] | None = None
) -> list[MortalDecision]:
    """指定席(省略時は4人全員)ぶんのMortalレビューをまとめて実行する。"""
    target_seats = list(seats) if seats is not None else [0, 1, 2, 3]
    decisions: list[MortalDecision] = []
    for seat in target_seats:
        decisions.extend(build_decisions_for_seat(game_log, seat, engine))
    return decisions

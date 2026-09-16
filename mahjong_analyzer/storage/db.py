"""SQLiteによる牌譜メタデータ・ミス検出結果・統計キャッシュの永続化。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from mahjong_analyzer.analysis.efficiency import DiscardMistake
from mahjong_analyzer.analysis.stats import PlayerStats
from mahjong_analyzer.parser.model import GameLog
from mahjong_analyzer.review.mortal_client import MortalDecision

_SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    paipu_id TEXT PRIMARY KEY,
    raw_path TEXT,
    fetched_at TEXT,
    parsed_at TEXT,
    start_time INTEGER,
    end_time INTEGER
);

CREATE TABLE IF NOT EXISTS players (
    paipu_id TEXT NOT NULL,
    seat INTEGER NOT NULL,
    name TEXT NOT NULL,
    account_id INTEGER,
    PRIMARY KEY (paipu_id, seat),
    FOREIGN KEY (paipu_id) REFERENCES games(paipu_id)
);

CREATE TABLE IF NOT EXISTS mistakes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paipu_id TEXT NOT NULL,
    kyoku_index INTEGER NOT NULL,
    turn INTEGER NOT NULL,
    actor INTEGER NOT NULL,
    discarded TEXT NOT NULL,
    shanten_before INTEGER NOT NULL,
    shanten_after_actual INTEGER NOT NULL,
    ukeire_after_actual INTEGER NOT NULL,
    best_discard TEXT NOT NULL,
    shanten_after_best INTEGER NOT NULL,
    ukeire_after_best INTEGER NOT NULL,
    dora_count_actual INTEGER NOT NULL DEFAULT 0,
    dora_count_best INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (paipu_id) REFERENCES games(paipu_id)
);

CREATE TABLE IF NOT EXISTS player_stats_cache (
    name TEXT PRIMARY KEY,
    games INTEGER NOT NULL,
    total_rank INTEGER NOT NULL,
    total_kyoku INTEGER NOT NULL,
    wins INTEGER NOT NULL,
    deal_ins INTEGER NOT NULL,
    riichi_count INTEGER NOT NULL,
    call_count INTEGER NOT NULL,
    win_score_total INTEGER NOT NULL,
    deal_in_score_total INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

-- Mortal AIとの比較によるEVベースの判断ポイント評価(押し引き/鳴き/リーチ等、
-- 複数の評価軸がここから異なる切り口で集計する共通データ)。
CREATE TABLE IF NOT EXISTS mortal_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paipu_id TEXT NOT NULL,
    kyoku_index INTEGER NOT NULL,
    turn INTEGER NOT NULL,
    actor INTEGER NOT NULL,
    decision_type TEXT NOT NULL,
    actual_choice TEXT NOT NULL,
    actual_q REAL NOT NULL,
    best_choice TEXT NOT NULL,
    best_q REAL NOT NULL,
    ev_loss REAL NOT NULL,
    shanten INTEGER,
    is_defending INTEGER NOT NULL DEFAULT 0,
    rank_at_decision INTEGER,
    is_all_last INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (paipu_id) REFERENCES games(paipu_id)
);
"""

# 既存DB(このカラム追加より前に作られたもの)向けのマイグレーション。
# SQLiteのCREATE TABLE IF NOT EXISTSは既存テーブルへのカラム追加をしないため、
# ALTER TABLEで個別に補う。
_MIGRATION_COLUMNS: dict[str, dict[str, str]] = {
    "games": {
        "start_time": "INTEGER",
        "end_time": "INTEGER",
    },
    "mistakes": {
        "dora_count_actual": "INTEGER NOT NULL DEFAULT 0",
        "dora_count_best": "INTEGER NOT NULL DEFAULT 0",
    },
}


def _migrate_tables(conn: sqlite3.Connection) -> None:
    for table, columns in _MIGRATION_COLUMNS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, sql_type in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    _migrate_tables(conn)
    return conn


@contextmanager
def open_db(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_fetched_game(conn: sqlite3.Connection, paipu_id: str, raw_path: str) -> None:
    conn.execute(
        """
        INSERT INTO games (paipu_id, raw_path, fetched_at)
        VALUES (?, ?, ?)
        ON CONFLICT(paipu_id) DO UPDATE SET raw_path = excluded.raw_path
        """,
        (paipu_id, raw_path, _now()),
    )


def record_parsed_game(conn: sqlite3.Connection, game_log: GameLog) -> None:
    conn.execute(
        """
        INSERT INTO games (paipu_id, parsed_at, start_time, end_time)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(paipu_id) DO UPDATE SET
            parsed_at = excluded.parsed_at,
            start_time = excluded.start_time,
            end_time = excluded.end_time
        """,
        (game_log.paipu_id, _now(), game_log.start_time, game_log.end_time),
    )
    conn.execute("DELETE FROM players WHERE paipu_id = ?", (game_log.paipu_id,))
    conn.executemany(
        "INSERT INTO players (paipu_id, seat, name, account_id) VALUES (?, ?, ?, ?)",
        [(game_log.paipu_id, p.seat, p.name, p.account_id) for p in game_log.players],
    )


def record_mistakes(conn: sqlite3.Connection, paipu_id: str, mistakes: list[DiscardMistake]) -> None:
    conn.execute("DELETE FROM mistakes WHERE paipu_id = ?", (paipu_id,))
    conn.executemany(
        """
        INSERT INTO mistakes (
            paipu_id, kyoku_index, turn, actor, discarded,
            shanten_before, shanten_after_actual, ukeire_after_actual,
            best_discard, shanten_after_best, ukeire_after_best,
            dora_count_actual, dora_count_best
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                paipu_id,
                m.kyoku_index,
                m.turn,
                m.actor,
                m.discarded,
                m.shanten_before,
                m.shanten_after_actual,
                m.ukeire_after_actual,
                m.best_discard,
                m.shanten_after_best,
                m.ukeire_after_best,
                m.dora_count_actual,
                m.dora_count_best,
            )
            for m in mistakes
        ],
    )


def record_player_stats(conn: sqlite3.Connection, stats: dict[str, PlayerStats]) -> None:
    conn.execute("DELETE FROM player_stats_cache")
    conn.executemany(
        """
        INSERT INTO player_stats_cache (
            name, games, total_rank, total_kyoku, wins, deal_ins,
            riichi_count, call_count, win_score_total, deal_in_score_total, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                s.name,
                s.games,
                s.total_rank,
                s.total_kyoku,
                s.wins,
                s.deal_ins,
                s.riichi_count,
                s.call_count,
                s.win_score_total,
                s.deal_in_score_total,
                _now(),
            )
            for s in stats.values()
        ],
    )


def list_paipu_ids(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT paipu_id FROM games ORDER BY fetched_at").fetchall()
    return [row["paipu_id"] for row in rows]


def fetch_mistakes(conn: sqlite3.Connection, paipu_id: str | None = None) -> list[sqlite3.Row]:
    if paipu_id is None:
        return conn.execute("SELECT * FROM mistakes ORDER BY paipu_id, kyoku_index, turn").fetchall()
    return conn.execute(
        "SELECT * FROM mistakes WHERE paipu_id = ? ORDER BY kyoku_index, turn",
        (paipu_id,),
    ).fetchall()


def mistake_from_row(row: sqlite3.Row) -> DiscardMistake:
    return DiscardMistake(
        kyoku_index=row["kyoku_index"],
        turn=row["turn"],
        actor=row["actor"],
        discarded=row["discarded"],
        shanten_before=row["shanten_before"],
        shanten_after_actual=row["shanten_after_actual"],
        ukeire_after_actual=row["ukeire_after_actual"],
        best_discard=row["best_discard"],
        shanten_after_best=row["shanten_after_best"],
        ukeire_after_best=row["ukeire_after_best"],
        dora_count_actual=row["dora_count_actual"],
        dora_count_best=row["dora_count_best"],
    )


def fetch_player_stats(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM player_stats_cache ORDER BY name").fetchall()


def record_mortal_decisions(
    conn: sqlite3.Connection, paipu_id: str, decisions: "list[MortalDecision]"
) -> None:
    conn.execute("DELETE FROM mortal_decisions WHERE paipu_id = ?", (paipu_id,))
    conn.executemany(
        """
        INSERT INTO mortal_decisions (
            paipu_id, kyoku_index, turn, actor, decision_type,
            actual_choice, actual_q, best_choice, best_q, ev_loss,
            shanten, is_defending, rank_at_decision, is_all_last
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                paipu_id,
                d.kyoku_index,
                d.turn,
                d.actor,
                d.decision_type,
                d.actual_choice,
                d.actual_q,
                d.best_choice,
                d.best_q,
                d.ev_loss,
                d.shanten,
                int(d.is_defending),
                d.rank_at_decision,
                int(d.is_all_last),
            )
            for d in decisions
        ],
    )


def fetch_mortal_decisions(
    conn: sqlite3.Connection, paipu_id: str | None = None
) -> list[sqlite3.Row]:
    if paipu_id is None:
        return conn.execute(
            "SELECT * FROM mortal_decisions ORDER BY paipu_id, kyoku_index, turn"
        ).fetchall()
    return conn.execute(
        "SELECT * FROM mortal_decisions WHERE paipu_id = ? ORDER BY kyoku_index, turn",
        (paipu_id,),
    ).fetchall()


def mortal_decision_from_row(row: sqlite3.Row) -> MortalDecision:
    return MortalDecision(
        kyoku_index=row["kyoku_index"],
        turn=row["turn"],
        actor=row["actor"],
        decision_type=row["decision_type"],
        actual_choice=row["actual_choice"],
        actual_q=row["actual_q"],
        best_choice=row["best_choice"],
        best_q=row["best_q"],
        shanten=row["shanten"],
        is_defending=bool(row["is_defending"]),
        rank_at_decision=row["rank_at_decision"],
        is_all_last=bool(row["is_all_last"]),
    )


def fetch_player_seats(conn: sqlite3.Connection, account_id: int) -> dict[str, int]:
    """account_idが対局(paipu_id)ごとにどの席に座っていたかを返す。

    自分自身の判断だけを評価軸の集計対象にする(他家の判断を混ぜない)ために使う。
    """
    rows = conn.execute(
        "SELECT paipu_id, seat FROM players WHERE account_id = ?", (account_id,)
    ).fetchall()
    return {row["paipu_id"]: row["seat"] for row in rows}


def known_names_for_account(conn: sqlite3.Connection, account_id: int) -> set[str]:
    """指定account_idが牌譜内で過去に名乗ったことのあるニックネーム一覧を返す
    (雀魂はニックネームを変更できるため、複数になり得る)。Web UIでユーザーネーム
    入力からaccount_idを解決する用途。"""
    rows = conn.execute("SELECT DISTINCT name FROM players WHERE account_id = ?", (account_id,))
    return {row["name"] for row in rows}


def fetch_games_with_times(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT paipu_id, start_time, end_time FROM games "
        "WHERE start_time IS NOT NULL ORDER BY start_time"
    ).fetchall()

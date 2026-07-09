"""บันทึกทุก signal/decision/trade/order ลง SQLite เพื่อตามรอยย้อนกลับได้เสมอ

ใช้ schema เดียวกันได้ทั้ง backtest (ตอนนี้) และ live runner (อนาคต) — run_id
แยกแต่ละรอบการรันออกจากกัน query ย้อนดูได้ว่า decision ไหนมาจาก signal ไหน
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from backtest.engine import Trade

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    strategy TEXT NOT NULL,
    started_at TEXT DEFAULT (datetime('now')),
    finished_at TEXT,
    initial_balance REAL,
    final_balance REAL,
    total_trades INTEGER,
    win_rate_pct REAL,
    profit_factor REAL,
    max_drawdown_pct REAL,
    expectancy REAL,
    halted_at TEXT,
    halt_reason TEXT,
    timeframe TEXT,
    config TEXT
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    bar_time TEXT NOT NULL,
    strategy TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry REAL, sl REAL, tp REAL,
    reason TEXT,
    discussion TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    signal_id INTEGER REFERENCES signals(id),
    approved INTEGER NOT NULL,
    reason TEXT,
    lot REAL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    signal_id INTEGER REFERENCES signals(id),
    direction TEXT NOT NULL,
    entry_time TEXT, entry REAL, sl REAL, tp REAL, lot REAL,
    exit_time TEXT, exit_price REAL, pnl REAL, outcome TEXT,
    regime TEXT,
    pnl_r REAL, mae_r REAL, mfe_r REAL, post_exit_r REAL,
    review TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    trade_id INTEGER REFERENCES trades(id),
    action TEXT NOT NULL,
    success INTEGER NOT NULL,
    ticket INTEGER,
    message TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


def _migrate_add_regime_column(conn: sqlite3.Connection) -> None:
    """เผื่อ DB เก่าที่สร้างก่อนมีคอลัมน์ใหม่ — ALTER TABLE ให้ทันสมัย"""
    migrations = {
        "trades": {
            "regime": "TEXT",
            "pnl_r": "REAL",
            "mae_r": "REAL",
            "mfe_r": "REAL",
            "post_exit_r": "REAL",
            "review": "TEXT",
        },
        "signals": {"discussion": "TEXT"},
        "runs": {"timeframe": "TEXT", "config": "TEXT"},
    }
    for table, columns in migrations.items():
        existing = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        for col, col_type in columns.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
    conn.commit()


class RunLogger:
    def __init__(self, db_path: str, run_id: str):
        self.run_id = run_id
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        _migrate_add_regime_column(self._conn)

    def start_run(
        self,
        strategy: str,
        initial_balance: float,
        timeframe: str | None = None,
        config: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO runs (run_id, strategy, started_at, initial_balance, timeframe, config) "
            "VALUES (?, ?, datetime('now'), ?, ?, ?)",
            (self.run_id, strategy, initial_balance, timeframe, config),
        )
        self._conn.commit()

    def finish_run(
        self,
        metrics: dict,
        halted_at=None,
        halt_reason: str = "",
    ) -> None:
        self._conn.execute(
            "UPDATE runs SET finished_at = datetime('now'), final_balance = ?, "
            "total_trades = ?, win_rate_pct = ?, profit_factor = ?, max_drawdown_pct = ?, "
            "expectancy = ?, halted_at = ?, halt_reason = ? WHERE run_id = ?",
            (
                metrics.get("final_balance"),
                metrics.get("total_trades"),
                metrics.get("win_rate_pct"),
                metrics.get("profit_factor"),
                metrics.get("max_drawdown_pct"),
                metrics.get("expectancy"),
                str(halted_at) if halted_at is not None else None,
                halt_reason,
                self.run_id,
            ),
        )
        self._conn.commit()

    def log_signal(
        self,
        bar_time,
        strategy: str,
        direction: str,
        entry,
        sl,
        tp,
        reason: str,
        discussion: str | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO signals (run_id, bar_time, strategy, direction, entry, sl, tp, reason, discussion) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (self.run_id, str(bar_time), strategy, direction, entry, sl, tp, reason, discussion),
        )
        self._conn.commit()
        return cur.lastrowid

    def log_decision(self, signal_id: int, approved: bool, reason: str, lot: float | None = None) -> int:
        cur = self._conn.execute(
            "INSERT INTO decisions (run_id, signal_id, approved, reason, lot) VALUES (?,?,?,?,?)",
            (self.run_id, signal_id, int(approved), reason, lot),
        )
        self._conn.commit()
        return cur.lastrowid

    def log_trade(self, signal_id: int, trade: "Trade") -> int:
        cur = self._conn.execute(
            "INSERT INTO trades (run_id, signal_id, direction, entry_time, entry, sl, tp, lot, "
            "exit_time, exit_price, pnl, outcome, regime, pnl_r, mae_r, mfe_r, post_exit_r, review) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                self.run_id,
                signal_id,
                trade.direction.value,
                str(trade.entry_time),
                trade.entry,
                trade.sl,
                trade.tp,
                trade.lot,
                str(trade.exit_time),
                trade.exit_price,
                trade.pnl,
                trade.outcome,
                trade.regime,
                getattr(trade, "pnl_r", None),
                getattr(trade, "mae_r", None),
                getattr(trade, "mfe_r", None),
                getattr(trade, "post_exit_r", None),
                getattr(trade, "review", None),
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def log_order(self, trade_id: int, action: str, success: bool, ticket: int | None = None, message: str = "") -> int:
        cur = self._conn.execute(
            "INSERT INTO orders (run_id, trade_id, action, success, ticket, message) VALUES (?,?,?,?,?,?)",
            (self.run_id, trade_id, action, int(success), ticket, message),
        )
        self._conn.commit()
        return cur.lastrowid

    def close(self) -> None:
        self._conn.close()


# --- query helpers (read-only, ใช้จาก dashboard.py หรือตอนวิเคราะห์ย้อนหลัง) ---


def _ensure_schema(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate_add_regime_column(conn)
    conn.close()


def list_runs(db_path: str) -> pd.DataFrame:
    _ensure_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        # rowid เป็น tiebreaker กรณีสอง run เริ่มภายในวินาทีเดียวกัน (started_at เท่ากัน)
        return pd.read_sql_query("SELECT * FROM runs ORDER BY started_at DESC, rowid DESC", conn)


def get_trades(db_path: str, run_id: str) -> pd.DataFrame:
    """เทรดทั้งหมดของ run พร้อมความเห็นคณะกรรมการ (discussion JSON) จาก signal ต้นทาง"""
    with sqlite3.connect(db_path) as conn:
        return pd.read_sql_query(
            "SELECT t.*, s.discussion FROM trades t "
            "LEFT JOIN signals s ON t.signal_id = s.id "
            "WHERE t.run_id = ? ORDER BY t.exit_time",
            conn,
            params=(run_id,),
        )


def get_decisions(db_path: str, run_id: str, approved: bool | None = None) -> pd.DataFrame:
    query = "SELECT * FROM decisions WHERE run_id = ?"
    params: list = [run_id]
    if approved is not None:
        query += " AND approved = ?"
        params.append(int(approved))
    with sqlite3.connect(db_path) as conn:
        return pd.read_sql_query(query, conn, params=params)


def get_signals(db_path: str, run_id: str) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        return pd.read_sql_query(
            "SELECT * FROM signals WHERE run_id = ? ORDER BY bar_time", conn, params=(run_id,)
        )

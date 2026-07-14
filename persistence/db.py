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


def _connect(db_path: str) -> sqlite3.Connection:
    """เปิด connection พร้อม timeout ยาว + WAL mode เสมอ — กัน 'database is locked' ตอนมีหลาย
    connection (live_runner 8 ทีม + dashboard backend) อ่าน/เขียนไฟล์เดียวกันพร้อมกัน"""
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    strategy TEXT NOT NULL,
    started_at TEXT DEFAULT (datetime('now')),
    finished_at TEXT,
    last_heartbeat TEXT,
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
    config TEXT,
    symbol TEXT
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
    ticket INTEGER,
    margin_used REAL,
    current_price REAL,
    floating_pnl REAL,
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

-- gate_state: เก็บ risk/live_gate.py::GateState ข้าม process restart — คีย์ด้วย (team, timeframe)
-- ไม่ใช่ run_id เพราะ run_id เปลี่ยนทุกครั้งที่ live_runner restart แต่ cooldown/probation/peak_balance
-- ต้อง "จำ" ข้ามการ restart ถึงจะมีความหมาย (ก่อนหน้านี้อยู่ใน memory ล้วนๆ รีเซ็ตทุกครั้งที่ process ตาย)
CREATE TABLE IF NOT EXISTS gate_state (
    team TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    balance REAL NOT NULL,
    peak_balance REAL NOT NULL,
    cal_date TEXT,
    cal_week TEXT,
    day_start_balance REAL,
    week_start_balance REAL,
    cooldown_until INTEGER,
    in_probation INTEGER NOT NULL DEFAULT 0,
    probation_events INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (team, timeframe)
);
"""


def find_open_trade(db_path: str, team: str, timeframe: str) -> dict | None:
    """หาไม้ที่ยังเปิดอยู่ (exit_time IS NULL) ล่าสุดของทีม/TF นี้ ข้าม run_id เดิม —
    ใช้ตอน bootstrap_team() restart เพื่อ "จำ" ไม้ที่ยังเปิดอยู่จริงใน MT5 กลับมา
    ไม่งั้น open_ticket จะเป็น None ตลอดไปหลัง restart ทำให้ reconcile_open_position()
    กลายเป็น no-op ถาวร (ราคาปัจจุบัน/กำไรลอยค้างค่าเดิมไม่อัปเดตอีกเลย)
    """
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT t.id, t.ticket, t.direction, t.entry, t.sl, t.tp, t.lot, t.entry_time, t.signal_id "
            "FROM trades t JOIN runs r ON t.run_id = r.run_id "
            "WHERE r.strategy = ? AND r.timeframe = ? AND t.exit_time IS NULL AND t.ticket IS NOT NULL "
            "ORDER BY t.id DESC LIMIT 1",
            (team, timeframe),
        ).fetchone()
        if row is None:
            return None
        cols = ["id", "ticket", "direction", "entry", "sl", "tp", "lot", "entry_time", "signal_id"]
        return dict(zip(cols, row))
    finally:
        conn.close()


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
            "ticket": "INTEGER",
            "margin_used": "REAL",
            "current_price": "REAL",
            "floating_pnl": "REAL",
        },
        "signals": {"discussion": "TEXT"},
        "runs": {"timeframe": "TEXT", "config": "TEXT", "last_heartbeat": "TEXT", "symbol": "TEXT"},
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
        # timeout=30 กัน "database is locked" ตอนหลายทีม (คนละ RunLogger คนละ connection)
        # เขียนพร้อมกัน — WAL mode ให้ writer/reader ทำงานพร้อมกันได้โดยไม่ล็อกทั้งไฟล์เหมือน
        # journal mode เดิม (DELETE) ซึ่งเคยทำให้ log_trade_open() ตอนเปิดไม้ throw แล้วไม้เปิดจริง
        # ใน MT5 ไม่มี record ใน DB เลย (exception โดนกลืนใน live_runner.py's broad except)
        self._conn = sqlite3.connect(db_path, timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        _migrate_add_regime_column(self._conn)

    def start_run(
        self,
        strategy: str,
        initial_balance: float,
        timeframe: str | None = None,
        config: str | None = None,
        symbol: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO runs (run_id, strategy, started_at, initial_balance, timeframe, config, symbol) "
            "VALUES (?, ?, datetime('now'), ?, ?, ?, ?)",
            (self.run_id, strategy, initial_balance, timeframe, config, symbol),
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

    def _execute_critical(self, sql: str, params: tuple, retries: int = 5) -> sqlite3.Cursor:
        """เหมือน self._conn.execute()+commit() ปกติ แต่ retry ด้วย backoff ถ้าเจอ 'database is locked'
        ใช้เฉพาะจุดที่ห้ามพลาดเด็ดขาด (log_trade_open/log_trade_close) — เพราะนี่คือ record เดียว
        ที่ยืนยันว่ามีไม้จริงเปิด/ปิดใน MT5 ถ้าเขียนไม่สำเร็จแล้วปล่อยผ่าน = ไม้หายจาก DB ถาวร
        ทั้งที่ยังเปิด/ปิดอยู่จริงใน broker (busy_timeout=30s ที่ตั้งไว้ตอน connect ควรกันเคสส่วนใหญ่
        อยู่แล้ว แต่ retry ชั้นนี้กันเคส contention รุนแรงที่ยาวกว่า 30s)
        """
        import time

        last_exc: sqlite3.OperationalError | None = None
        for attempt in range(retries):
            try:
                cur = self._conn.execute(sql, params)
                self._conn.commit()
                return cur
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                last_exc = exc
                time.sleep(0.5 * (attempt + 1))
        raise last_exc  # type: ignore[misc]

    def log_trade_open(
        self,
        signal_id: int,
        direction: str,
        entry_time,
        entry: float,
        sl: float,
        tp: float,
        lot: float,
        ticket: int | None = None,
        margin_used: float | None = None,
        regime: str | None = None,
    ) -> int:
        """บันทึกไม้ตอนเปิด (exit_time ยังว่าง) — ให้ dashboard เห็นไม้ที่ยังเปิดอยู่แบบ real-time
        แทนที่จะรอให้ไม้ปิดก่อนถึงจะมี record (ต่างจาก log_trade ที่ backtest ใช้ insert ครั้งเดียวตอนปิด)
        """
        cur = self._execute_critical(
            "INSERT INTO trades (run_id, signal_id, direction, entry_time, entry, sl, tp, lot, "
            "ticket, margin_used, regime) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (self.run_id, signal_id, direction, str(entry_time), entry, sl, tp, lot, ticket, margin_used, regime),
        )
        return cur.lastrowid

    def update_open_trade(self, trade_id: int, current_price: float | None, floating_pnl: float | None) -> None:
        """อัปเดตราคาปัจจุบัน/กำไรลอยของไม้ที่ยังเปิดอยู่ — เรียกทุกรอบ poll"""
        self._conn.execute(
            "UPDATE trades SET current_price = ?, floating_pnl = ? WHERE id = ?",
            (current_price, floating_pnl, trade_id),
        )
        self._conn.commit()

    def log_trade_close(
        self,
        trade_id: int,
        exit_time,
        exit_price: float,
        pnl: float,
        outcome: str,
    ) -> None:
        """ปิด record ไม้ที่เปิดไว้จาก log_trade_open — เติม exit fields ให้ครบ"""
        self._execute_critical(
            "UPDATE trades SET exit_time = ?, exit_price = ?, pnl = ?, outcome = ?, "
            "current_price = NULL, floating_pnl = NULL WHERE id = ?",
            (str(exit_time), exit_price, pnl, outcome, trade_id),
        )

    def log_order(self, trade_id: int, action: str, success: bool, ticket: int | None = None, message: str = "") -> int:
        cur = self._conn.execute(
            "INSERT INTO orders (run_id, trade_id, action, success, ticket, message) VALUES (?,?,?,?,?,?)",
            (self.run_id, trade_id, action, int(success), ticket, message),
        )
        self._conn.commit()
        return cur.lastrowid

    def update_heartbeat(self) -> None:
        """อัปเดตเวลา heartbeat ล่าสุด — เรียกทุกครั้งที่ live_runner poll bar ใหม่"""
        self._conn.execute(
            "UPDATE runs SET last_heartbeat = datetime('now') WHERE run_id = ?",
            (self.run_id,),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


# --- query helpers (read-only, ใช้จาก dashboard.py หรือตอนวิเคราะห์ย้อนหลัง) ---


def _ensure_schema(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate_add_regime_column(conn)
    conn.close()


def list_runs(db_path: str) -> pd.DataFrame:
    _ensure_schema(db_path)
    with _connect(db_path) as conn:
        # rowid เป็น tiebreaker กรณีสอง run เริ่มภายในวินาทีเดียวกัน (started_at เท่ากัน)
        return pd.read_sql_query("SELECT * FROM runs ORDER BY started_at DESC, rowid DESC", conn)


def get_trades(db_path: str, run_id: str) -> pd.DataFrame:
    """เทรดทั้งหมดของ run พร้อมเหตุผลเข้าไม้ (reason) + ความเห็นคณะกรรมการ (discussion JSON) จาก signal ต้นทาง"""
    with _connect(db_path) as conn:
        return pd.read_sql_query(
            "SELECT t.*, s.reason, s.discussion FROM trades t "
            "LEFT JOIN signals s ON t.signal_id = s.id "
            "WHERE t.run_id = ? ORDER BY t.entry_time",
            conn,
            params=(run_id,),
        )


def get_decisions(db_path: str, run_id: str, approved: bool | None = None) -> pd.DataFrame:
    query = "SELECT * FROM decisions WHERE run_id = ?"
    params: list = [run_id]
    if approved is not None:
        query += " AND approved = ?"
        params.append(int(approved))
    with _connect(db_path) as conn:
        return pd.read_sql_query(query, conn, params=params)


def get_signals(db_path: str, run_id: str) -> pd.DataFrame:
    with _connect(db_path) as conn:
        return pd.read_sql_query(
            "SELECT * FROM signals WHERE run_id = ? ORDER BY bar_time", conn, params=(run_id,)
        )


def save_gate_state(db_path: str, team: str, timeframe: str, state) -> None:
    """บันทึก GateState (cooldown/probation/peak_balance) ข้าม process restart — คีย์ (team, timeframe)
    เรียกทุกรอบ poll จาก live_runner.py กันไม่ให้การป้องกันความเสี่ยงหายไปตอน process ตาย/restart
    """
    import json as _json

    # ตั้งชื่อคอลัมน์ cal_date/cal_week (ไม่ใช่ current_date/current_week) เพราะ CURRENT_DATE เป็น
    # keyword พิเศษของ SQLite (literal-value token คืนวันที่วันนี้) — ใช้ current_date เป็นชื่อคอลัมน์
    # ตรงๆ ทำให้ SQLite แอบแทนที่ค่าที่ INSERT ด้วยวันที่ปัจจุบันเงียบๆ แทนที่จะเก็บค่าที่ส่งมาจริง
    # (เจอบั๊กนี้ตอนเขียน — ทดสอบแล้วว่า rename แก้ได้เด็ดขาด)
    _ensure_schema(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO gate_state (team, timeframe, balance, peak_balance, cal_date, "
            "cal_week, day_start_balance, week_start_balance, cooldown_until, in_probation, "
            "probation_events, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now')) "
            "ON CONFLICT(team, timeframe) DO UPDATE SET "
            "balance=excluded.balance, peak_balance=excluded.peak_balance, "
            "cal_date=excluded.cal_date, cal_week=excluded.cal_week, "
            "day_start_balance=excluded.day_start_balance, week_start_balance=excluded.week_start_balance, "
            "cooldown_until=excluded.cooldown_until, in_probation=excluded.in_probation, "
            "probation_events=excluded.probation_events, updated_at=datetime('now')",
            (
                team, timeframe, state.balance, state.peak_balance,
                state.current_date.isoformat() if state.current_date else None,
                _json.dumps(list(state.current_week)) if state.current_week else None,
                state.day_start_balance, state.week_start_balance,
                state.cooldown_until, int(state.in_probation), state.probation_events,
            ),
        )
        conn.commit()


def load_gate_state(db_path: str, team: str, timeframe: str):
    """โหลด GateState ที่บันทึกไว้ล่าสุดของ (team, timeframe) — คืน None ถ้าไม่เคยมี (ทีมใหม่)"""
    import json as _json
    from datetime import date as _date

    from risk.live_gate import GateState

    _ensure_schema(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT balance, peak_balance, cal_date, cal_week, day_start_balance, "
            "week_start_balance, cooldown_until, in_probation, probation_events "
            "FROM gate_state WHERE team = ? AND timeframe = ?",
            (team, timeframe),
        ).fetchone()
    if row is None:
        return None
    (balance, peak_balance, cal_date_str, cal_week_str, day_start_balance,
     week_start_balance, cooldown_until, in_probation, probation_events) = row
    return GateState(
        balance=balance,
        peak_balance=peak_balance,
        current_date=_date.fromisoformat(cal_date_str) if cal_date_str else None,
        current_week=tuple(_json.loads(cal_week_str)) if cal_week_str else None,
        day_start_balance=day_start_balance or 0.0,
        week_start_balance=week_start_balance or 0.0,
        cooldown_until=cooldown_until if cooldown_until is not None else -1,
        in_probation=bool(in_probation),
        probation_events=probation_events or 0,
    )

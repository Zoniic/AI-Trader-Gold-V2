import math

from fastapi.testclient import TestClient

from backtest.engine import Trade
from core.signal import Direction
from persistence.db import RunLogger
from web.backend import main as api_main


def _seed_db(db_path: str) -> None:
    logger = RunLogger(db_path, run_id="run_api_test")
    logger.start_run("ema_cross", initial_balance=10000.0)
    signal_id = logger.log_signal(
        bar_time="2024-01-01 00:00:00",
        strategy="ema_cross",
        direction="BUY",
        entry=1950.0,
        sl=1945.0,
        tp=1960.0,
        reason="test",
    )
    logger.log_decision(signal_id, approved=True, reason="ok", lot=0.1)
    trade = Trade(
        direction=Direction.BUY,
        entry_time="2024-01-01 00:00:00",
        entry=1950.0,
        sl=1945.0,
        tp=1960.0,
        lot=0.1,
        exit_time="2024-01-01 05:00:00",
        exit_price=1960.0,
        pnl=100.0,
        outcome="tp",
    )
    logger.log_trade(signal_id, trade)

    rejected_signal_id = logger.log_signal(
        bar_time="2024-01-02 00:00:00",
        strategy="ema_cross",
        direction="SELL",
        entry=1955.0,
        sl=1955.0,
        tp=1945.0,
        reason="test2",
    )
    logger.log_decision(rejected_signal_id, approved=False, reason="sl_distance ต้องมากกว่า 0")

    logger.finish_run(
        {
            "final_balance": 10100.0,
            "total_trades": 1,
            "win_rate_pct": 100.0,
            "profit_factor": float("inf"),  # เจตนาเทสต์ค่า inf ให้ sanitize เป็น None
            "max_drawdown_pct": 0.0,
            "expectancy": 100.0,
        },
        halted_at=None,
        halt_reason="",
    )
    logger.close()


def test_list_runs_endpoint(tmp_path, monkeypatch):
    db_path = str(tmp_path / "api_test.db")
    _seed_db(db_path)

    settings = api_main.load_settings()
    monkeypatch.setattr(
        api_main, "load_settings", lambda: settings.__class__(**{**settings.__dict__, "log_db_path": db_path})
    )

    client = TestClient(api_main.app)
    resp = client.get("/runs")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["run_id"] == "run_api_test"
    assert body[0]["profit_factor"] is None  # inf ต้องถูกแปลงเป็น None ไม่ใช่ literal Infinity


def test_run_detail_endpoint(tmp_path, monkeypatch):
    db_path = str(tmp_path / "api_test2.db")
    _seed_db(db_path)

    settings = api_main.load_settings()
    monkeypatch.setattr(
        api_main, "load_settings", lambda: settings.__class__(**{**settings.__dict__, "log_db_path": db_path})
    )

    client = TestClient(api_main.app)
    resp = client.get("/runs/run_api_test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run"]["run_id"] == "run_api_test"
    assert len(body["trades"]) == 1
    assert body["trades"][0]["pnl"] == 100.0
    assert body["rejected_count"] == 1
    assert body["rejected_reasons"][0]["reason"] == "sl_distance ต้องมากกว่า 0"

    # ยืนยันว่า response ทั้งก้อน serialize เป็น JSON ที่ถูกต้อง (ไม่มี NaN/Infinity literal หลุดออกมา)
    raw_text = resp.text
    assert "NaN" not in raw_text
    assert "Infinity" not in raw_text


def test_run_detail_404_for_missing_run(monkeypatch, tmp_path):
    db_path = str(tmp_path / "empty.db")
    settings = api_main.load_settings()
    monkeypatch.setattr(
        api_main, "load_settings", lambda: settings.__class__(**{**settings.__dict__, "log_db_path": db_path})
    )
    client = TestClient(api_main.app)
    resp = client.get("/runs/does_not_exist")
    assert resp.status_code == 404
